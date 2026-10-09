# -*- coding: utf-8 -*-
"""真实后端工作线程：登录 / 课程列表 / 作业 / 资料树 / 下载。

约定：耗时操作一律放 QThread，结果用信号回传 UI 线程；风控（412/403/429）
与会话失效在各 worker run() 内捕获转信号，绝不跨线程抛异常。
红线：worker 只处理调用方显式传入的课程对象（未选课程零请求）。
"""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.core import browser, downloader
from app.core.api import courses as courses_api
from app.core.api import homework as homework_api
from app.core.api import materials as materials_api
from app.core.session import ChaoxingSession, RiskControlError, SessionExpiredError
from app.core.storage import Storage


class LoginWorker(QThread):
    """登录线程：Cookie 缓存优先，缺失/失效时 DrissionPage + 系统 Edge/Chrome 手动 CAS 登录。"""

    STEPS = [
        "读取本地 Cookie 缓存（DPAPI 加密）",
        "启动浏览器（Edge/Chrome）打开统一身份认证",
        "等待手动完成 CAS 登录",
        "缓存会话 Cookie（DPAPI 加密）",
    ]
    step_changed = Signal(int, str)        # (步骤序号, running|done)
    login_success = Signal(object, str)    # (ChaoxingSession, 用户展示名)
    login_failed = Signal(str)

    def __init__(self, parent=None, auto: bool = False):
        super().__init__(parent)
        self._auto = auto        # auto=True：仅尝试本地缓存，缺缓存不弹浏览器
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        self.step_changed.emit(0, "running")
        if self._auto:
            # 自动模式：仅尝试本地缓存，缺缓存不弹浏览器
            cookies = browser.load_cookies()
            if cookies and "vc3" in cookies:
                self.step_changed.emit(0, "done")
                self.step_changed.emit(1, "done")   # 缓存命中：免开浏览器
                self.step_changed.emit(2, "done")
                self._finish(cookies)
                return
            self.step_changed.emit(0, "done")
            self.login_failed.emit("未检测到有效登录缓存")
            return

        # 手动模式（点击“启动浏览器登录/重新登录”）：忽略缓存，直接弹浏览器
        self.step_changed.emit(0, "done")
        self.step_changed.emit(1, "running")
        try:
            result = browser.login_interactive(should_stop=lambda: self._stop)
        except browser.BrowserNotFoundError as e:
            self.login_failed.emit(str(e))
            return
        except browser.LoginTimeoutError as e:
            self.login_failed.emit(str(e))
            return
        except Exception as e:  # DrissionPage 启动失败等环境问题
            self.login_failed.emit(f"浏览器登录失败：{type(e).__name__}: {e}")
            return
        if result is None:  # 用户取消（浏览器已由 finally 关闭）
            self.login_failed.emit("已取消登录")
            return
        cookies, _ua = result
        self.step_changed.emit(1, "done")
        self.step_changed.emit(2, "done")

        self.step_changed.emit(3, "running")
        browser.save_cookies(cookies)
        self.step_changed.emit(3, "done")
        self._finish(cookies)

    def _finish(self, cookies: dict):
        ses = ChaoxingSession(cookies)   # httpx.Client 线程安全，可跨 worker 复用
        uid = str(cookies.get("_uid", "")).strip()
        self.login_success.emit(ses, f"用户 {uid}" if uid else "已登录")


class CourseListWorker(QThread):
    """课程列表线程：登录后唯一自动发起的请求（仅拉列表，不碰任何课程数据）。"""

    course_list = Signal(list)       # list[Course]（含未选课程，仅供“管理课程”展示）
    session_expired = Signal()
    risk_stopped = Signal(str)
    failed = Signal(str)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session

    def run(self):
        try:
            self.course_list.emit(courses_api.fetch_course_list(self._session))
        except SessionExpiredError:
            self.session_expired.emit()
        except RiskControlError as e:
            self.risk_stopped.emit(str(e))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class HomeworkWorker(QThread):
    """作业线程：逐课 open_study_page → fetch_homework（顺带产出 stuenc 供下载复用）。"""

    homework_ready = Signal(str, str, str, list)   # (course_key, 课程名, stuenc, [Homework])
    course_error = Signal(str, str)                # (course_key, 错误摘要)——跳过该课继续
    session_expired = Signal()
    risk_stopped = Signal(str)
    finished = Signal()

    def __init__(self, session, course_list: list, parent=None):
        super().__init__(parent)
        self._session = session
        self._courses = list(course_list)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            for course in self._courses:
                if self._stop:
                    break
                key = courses_api.course_key(course)
                try:
                    ctx = courses_api.open_study_page(self._session, course)
                    items = homework_api.fetch_homework(self._session, ctx.work_list_url)
                except SessionExpiredError:
                    raise
                except RiskControlError:
                    raise
                except Exception as e:
                    self.course_error.emit(key, f"{type(e).__name__}: {e}")
                    continue
                self.homework_ready.emit(key, course.name, ctx.stuenc, items)
        except SessionExpiredError:
            self.session_expired.emit()
        except RiskControlError as e:
            self.risk_stopped.emit(str(e))
        finally:
            self.finished.emit()


class TreeWorker(QThread):
    """资料树线程：picker 选中课程后按需拉取整棵资料树（懒加载，一课一线程）。"""

    tree_ready = Signal(str, str, list, list)   # (course_key, stuenc, roots, todos)
    failed = Signal(str, str)             # (course_key, 错误摘要)
    session_expired = Signal()
    risk_stopped = Signal(str)

    def __init__(self, session, course, parent=None):
        super().__init__(parent)
        self._session = session
        self._course = course
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        key = courses_api.course_key(self._course)
        try:
            ctx = courses_api.open_study_page(self._session, self._course)
            if self._stop:            # 退出中：不再发起后续资料树抓取
                return
            tree = materials_api.fetch_tree(self._session, self._course, ctx.stuenc)
            self.tree_ready.emit(key, ctx.stuenc, tree.roots, tree.todos)
        except SessionExpiredError:
            self.session_expired.emit()
        except RiskControlError as e:
            self.risk_stopped.emit(str(e))
        except Exception as e:
            self.failed.emit(key, f"{type(e).__name__}: {e}")


class DownloadWorker(QThread):
    """下载线程：真实下载器顺序落盘，核心回调转发为信号。"""

    task_started = Signal(int)               # row（首个进度块到达时触发）
    task_progress = Signal(int, int)         # (row, percent)；percent<0 表示大小未知（忙碌）
    task_finished = Signal(int, str, str)    # (row, status, detail)
    all_finished = Signal(int, int, int)     # done, skipped, other
    session_expired = Signal()
    risk_stopped = Signal(str)

    def __init__(self, session, course, files: list, stuenc: str, root, parent=None):
        super().__init__(parent)
        self._session = session
        self._course = course
        self._files = list(files)
        self._stuenc = stuenc
        self._root = Path(root)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        storage = Storage()   # sqlite 连接必须在使用线程内创建（check_same_thread 默认限制）
        report = downloader.DownloadReport()
        row_of = {nd.relative_path: i for i, nd in enumerate(self._files)}
        referer = materials_api.root_url(self._course, self._stuenc)
        stats = {"done": 0, "skip": 0, "other": 0}
        finished_rows = set()
        started_rows = set()

        def on_result(node, result):
            row = row_of.get(node.relative_path)
            if row is None:
                return
            finished_rows.add(row)
            if result.status in ("done", "updated"):
                stats["done"] += 1
            elif result.status.startswith("skip"):
                stats["skip"] += 1
            else:
                stats["other"] += 1
            self.task_finished.emit(row, result.status, result.detail)

        def on_progress(node, written, total):
            row = row_of.get(node.relative_path)
            if row is None:
                return
            if row not in started_rows:
                started_rows.add(row)
                self.task_started.emit(row)   # 首个数据块到达 → “下载中”
            self.task_progress.emit(
                row, int(written * 100 / total) if total > 0 else -1)

        try:
            downloader.download_course(
                self._session, self._course, self._files, storage, referer, report,
                root=self._root, on_result=on_result, on_progress=on_progress,
                should_stop=lambda: self._stop)
        except SessionExpiredError:
            self.session_expired.emit()
        except RiskControlError as e:
            self.risk_stopped.emit(str(e))
        finally:
            # 兜底：会话失效/风控中止时仍有行未产出结果，保证统计一致
            for row in range(len(self._files)):
                if row not in finished_rows:
                    self.task_finished.emit(row, "cancelled", "已中止（会话失效或风控停止）")
            storage.close()
            self.all_finished.emit(stats["done"], stats["skip"], stats["other"])
