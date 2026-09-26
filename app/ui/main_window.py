# -*- coding: utf-8 -*-
"""主窗口：侧边导航（资料下载 / 下载管理 / 作业列表）+ 登录引导主界面（真实后端）。

数据策略（2026-09-26 定稿）：
- 登录后仅拉课程列表；「管理课程」勾选需要关注的课程（QSettings 持久化）
- 已选课程作业数据每次启动自动后台拉取（逐课渐进）；资料树选中课程时才拉取
- 未选课程零网络请求；命中风控立即停止；会话失效统一回登录页
"""
import json

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from app.core import browser
from app.core.api import courses as courses_api
from app.ui import icons
from app.ui.dialogs import CloseConfirmDialog, CourseManageDialog
from app.ui.pages.download_page import DownloadPage
from app.ui.pages.homework_page import HomeworkPage
from app.ui.pages.login_page import LoginPage
from app.ui.pages.materials_page import MaterialsPage
from app.ui.widgets import NavButton, ToastHost, UserChip
from app.ui.workers import (
    CourseListWorker, DownloadWorker, HomeworkWorker, TreeWorker,
)

PAGES = [("materials", "📚  资料下载"), ("downloads", "⬇️  下载管理"), ("homework", "📝  作业列表")]

SELECTED_KEY = "courses/selected"   # QSettings：已选课程 key（JSON 数组，courseId|clazzId）


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("东方理工 LMS 助手")

        self._settings = QSettings("eitech", "lms-helper")
        self._session = None
        self._all_courses = []           # 平台全量课程（仅供管理课程展示）
        self._subscribed: set = self._load_selected()
        self._hw_by_key: dict = {}       # course_key -> (课程名, [Homework])
        self._hw_requested: set = set()  # 已派发给 HomeworkWorker 的 course_key
        self._pending_hw: list = []      # 选课新增、待补拉的 Course
        self._stuenc: dict = {}          # course_key -> stuenc（下载 referer 用）
        self._homework_worker = None
        self._course_list_worker = None
        self._tree_workers: dict = {}    # course_key -> TreeWorker

        self._force_quit = False         # 托盘「退出」/弹窗「完全退出」置位后 closeEvent 直接清理
        self._close_action = str(self._settings.value("close/action", "ask"))
        if self._close_action not in ("ask", "tray", "exit"):
            self._close_action = "ask"

        self.setWindowIcon(icons.app_icon())
        central = QWidget()
        central.setObjectName("Page")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())
        lay.addWidget(self._build_stack(), 1)
        self.setCentralWidget(central)

        self._toast_host = ToastHost(self)

        self._build_tray()
        self._wire_signals()
        self.show_page("login")          # 未登录：登录引导即主界面
        self._login_page.start_auto()    # 启动即尝试本地缓存自动登录（不弹浏览器）

    # ---------- 侧边栏 ----------

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 22, 14, 16)
        lay.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        dot = QLabel()
        dot.setObjectName("BrandDot")
        dot.setFixedSize(10, 10)
        name = QLabel("东方理工 LMS 助手")
        name.setObjectName("Brand")
        brand_row.addWidget(dot)
        brand_row.addWidget(name)
        brand_row.addStretch(1)
        lay.addLayout(brand_row)

        sub = QLabel("超星“资料”批量下载 · 桌面版")
        sub.setObjectName("BrandSub")
        lay.addWidget(sub)
        lay.addSpacing(18)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav: dict = {}
        for key, text in PAGES:
            btn = NavButton(text)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self._nav_group.addButton(btn)
            self._nav[key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)
        badge = QLabel("仅访问超星只读接口\n下载全程随机限速")
        badge.setObjectName("DemoBadge")
        badge.setWordWrap(True)
        lay.addWidget(badge)
        lay.addSpacing(8)
        self._user_chip = UserChip()
        lay.addWidget(self._user_chip)
        return side

    def _build_stack(self) -> QStackedWidget:
        self._stack = QStackedWidget()
        self._login_page = LoginPage()
        self._materials_page = MaterialsPage(toast=self.toast)
        self._download_page = DownloadPage(toast=self.toast)
        self._homework_page = HomeworkPage(toast=self.toast)
        for page in (self._login_page, self._materials_page,
                     self._download_page, self._homework_page):
            self._stack.addWidget(page)
        return self._stack

    # ---------- 选课持久化 ----------

    def _load_selected(self) -> set:
        raw = self._settings.value(SELECTED_KEY, "")
        if not raw:
            return set()
        try:
            data = json.loads(raw)
        except ValueError:
            return set()
        return {str(k) for k in data} if isinstance(data, list) else set()

    def _save_selected(self):
        self._settings.setValue(SELECTED_KEY, json.dumps(sorted(self._subscribed)))

    # ---------- 信号装配 ----------

    def _wire_signals(self):
        self._login_page.login_success.connect(self._on_login_success)
        self._user_chip.clicked.connect(lambda: self.show_page("login"))
        self._materials_page.course_selected.connect(self._on_course_selected)
        self._materials_page.manage_requested.connect(self._open_course_manager)
        self._materials_page.download_requested.connect(self._start_download)
        self._download_page.tasks_changed.connect(self._nav["downloads"].set_badge)
        self._download_page.session_expired.connect(self._on_session_expired)
        self._download_page.risk_stopped.connect(self._on_risk_stopped)
        self._homework_page.counts_changed.connect(self._nav["homework"].set_badge)
        self._homework_page.refresh_requested.connect(self._refresh_homework)

    # ---------- 登录 → 课程列表 ----------

    def _on_login_success(self, session, display_name: str):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = session
        self._reset_data()               # 重新登录一律按新会话重建数据
        self._user_chip.set_user(display_name)
        self.toast("登录成功，Cookie 已缓存")
        QTimer.singleShot(900, lambda: self.show_page("materials"))
        self._start_course_list()

    def _reset_data(self):
        self._hw_by_key = {}
        self._hw_requested = set()
        self._pending_hw = []
        self._stuenc = {}
        self._materials_page.set_courses([])
        self._homework_page.set_data({})

    def _start_course_list(self):
        self._course_list_worker = CourseListWorker(self._session, self)
        w = self._course_list_worker
        w.course_list.connect(self._on_course_list)
        w.session_expired.connect(self._on_session_expired)
        w.risk_stopped.connect(self._on_risk_stopped)
        w.failed.connect(lambda m: self.toast(f"课程列表获取失败：{m}"))
        w.start()

    def _on_course_list(self, course_list: list):
        self._all_courses = list(course_list)
        subscribed = [c for c in self._all_courses
                      if courses_api.course_key(c) in self._subscribed]
        self._materials_page.set_courses(subscribed)   # 内部会触发首课 course_selected
        if subscribed:
            self._start_homework_worker(subscribed)
        else:
            self.toast("尚未选择课程：点击课程框 → ⚙ 管理课程 添加关注课程")

    # ---------- 作业（已选课程，逐课渐进） ----------

    def _start_homework_worker(self, course_list: list):
        self._homework_page.set_refreshing(True)
        if self._homework_worker and self._homework_worker.isRunning():
            have = {courses_api.course_key(c) for c in self._pending_hw}
            self._pending_hw.extend(
                c for c in course_list if courses_api.course_key(c) not in have)
            return
        self._hw_requested.update(courses_api.course_key(c) for c in course_list)
        self._homework_worker = HomeworkWorker(self._session, course_list, self)
        w = self._homework_worker
        w.homework_ready.connect(self._on_homework_ready)
        w.course_error.connect(lambda k, m: self.toast(f"作业获取失败：{m}"))
        w.session_expired.connect(self._on_session_expired)
        w.risk_stopped.connect(self._on_risk_stopped)
        w.finished.connect(self._on_homework_batch_done)
        w.start()

    def _refresh_homework(self):
        """手动刷新：强制重拉全部已选课程（不受 _hw_requested 去重限制）。"""
        if self._session is None:
            self.toast("请先登录")
            return
        subscribed = [c for c in self._all_courses
                      if courses_api.course_key(c) in self._subscribed]
        if not subscribed:
            self.toast("尚未选择课程：点击课程框 → ⚙ 管理课程 添加关注课程")
            return
        self._start_homework_worker(subscribed)

    def _on_homework_batch_done(self):
        if self._pending_hw:
            batch, self._pending_hw = self._pending_hw, []
            self._start_homework_worker(batch)
        else:
            self._homework_page.set_refreshing(False)

    def _on_homework_ready(self, key: str, name: str, stuenc: str, items: list):
        if key not in self._subscribed:   # 期间被移除的课程：丢弃结果
            return
        self._hw_by_key[key] = (name, list(items))
        if stuenc:
            self._stuenc[key] = stuenc
        self._refresh_homework_page()

    def _refresh_homework_page(self):
        data: dict = {}
        for name, items in self._hw_by_key.values():
            data.setdefault(name, []).extend(items)
        self._homework_page.set_data(data)

    # ---------- 资料树（选中课程按需拉取） ----------

    def _on_course_selected(self, course):
        if self._session is None:
            return
        if not self._materials_page.begin_load_if_needed(course):
            return
        key = courses_api.course_key(course)
        w = TreeWorker(self._session, course, self)
        self._tree_workers[key] = w
        w.tree_ready.connect(self._on_tree_ready)
        w.failed.connect(self._on_tree_failed)
        w.session_expired.connect(self._on_session_expired)
        w.risk_stopped.connect(self._on_risk_stopped)
        w.start()

    def _on_tree_ready(self, key: str, stuenc: str, roots: list, todos: list):
        self._tree_workers.pop(key, None)
        if key not in self._subscribed:
            return
        if stuenc:
            self._stuenc[key] = stuenc
        self._materials_page.set_course_roots(key, roots)
        for t in todos:                   # 分页达上限等完整性告警
            self.toast(f"告警：{t}")

    def _on_tree_failed(self, key: str, err: str):
        self._tree_workers.pop(key, None)
        self._materials_page.set_course_roots(key, [], error=err)

    # ---------- 管理课程 ----------

    def _open_course_manager(self):
        if self._session is None or not self._all_courses:
            self.toast("请先登录以获取课程列表")
            return
        dlg = CourseManageDialog(self._all_courses, self._subscribed, self)
        if not dlg.exec():
            return
        selected = dlg.selected_keys()
        removed = self._subscribed - selected
        self._subscribed = selected
        self._save_selected()
        for k in removed:                 # 移除课程：清缓存，之后零请求
            self._hw_by_key.pop(k, None)
            self._stuenc.pop(k, None)
            self._hw_requested.discard(k)
        subscribed_courses = [c for c in self._all_courses
                              if courses_api.course_key(c) in self._subscribed]
        self._materials_page.set_courses(subscribed_courses)
        self._refresh_homework_page()
        added = [c for c in subscribed_courses
                 if courses_api.course_key(c) not in self._hw_requested]
        if added:
            self._start_homework_worker(added)
        self.toast(f"课程选择已保存：共 {len(selected)} 门")

    # ---------- 下载 ----------

    def _start_download(self, files: list):
        course = self._materials_page.current_course()
        if course is None or self._session is None:
            return
        key = courses_api.course_key(course)
        worker = DownloadWorker(self._session, course, files,
                                self._stuenc.get(key, ""),
                                self._materials_page.download_dir)
        self._download_page.start_tasks(files, worker)
        self.show_page("downloads")

    # ---------- 会话失效 / 风控 ----------

    def _on_session_expired(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None
        browser.discard_cookies()
        self._pending_hw = []
        self._homework_page.set_refreshing(False)
        self._reset_data()
        self._user_chip.set_user("未登录")
        self.toast("登录已失效，请重新登录")
        self.show_page("login")

    def _on_risk_stopped(self, message: str):
        self.toast(f"已停止：命中平台风控，请稍后再试（{message}）")

    # ---------- 系统托盘 ----------

    def _build_tray(self):
        """托盘常驻图标：左键/双击恢复窗口；右键菜单含关闭行为三选一与退出。"""
        self._tray = QSystemTrayIcon(icons.app_icon(), self)
        menu = QMenu(self)
        menu.setObjectName("TrayMenu")
        menu.setWindowFlags(menu.windowFlags()
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 否则圆角四角露出系统矩形底
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._restore_from_tray)
        menu.addSeparator()

        self._close_menu_actions: dict = {}
        group = QActionGroup(menu)       # 关闭行为三选一互斥，避免记住 exit 后无法改回
        for value, text in (("ask", "关闭时询问"), ("tray", "关闭时最小化到托盘"),
                            ("exit", "关闭时直接退出")):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, v=value: self._set_close_action(v))
            group.addAction(act)
            self._close_menu_actions[value] = act
        self._sync_close_menu()

        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _sync_close_menu(self):
        for value, act in self._close_menu_actions.items():
            act.setChecked(value == self._close_action)

    def _set_close_action(self, value: str):
        self._close_action = value
        self._settings.setValue("close/action", value)
        self._sync_close_menu()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.activateWindow()
        self.raise_()

    def _quit_app(self):
        """托盘退出：窗口隐藏时 close() 不会触发 lastWindowClosed，必须显式清理并退出。"""
        self._force_quit = True
        self._teardown()
        QApplication.instance().quit()

    def _ask_close_action(self) -> str | None:
        """弹窗询问关闭行为；取消返回 None。勾选记住时写 QSettings。"""
        dlg = CloseConfirmDialog(
            downloading=self._download_page.has_active_downloads(),
            tray_available=QSystemTrayIcon.isSystemTrayAvailable(),
            parent=self)
        if not dlg.exec() or dlg.choice is None:
            return None
        if dlg.remember():
            self._set_close_action(dlg.choice)
        return dlg.choice

    # ---------- 导航 / Toast / 生命周期 ----------

    def show_page(self, name: str):
        index = {"login": 0, "materials": 1, "downloads": 2, "homework": 3}[name]
        self._stack.setCurrentIndex(index)
        for key, btn in self._nav.items():
            btn.setChecked(key == name)

    def toast(self, text: str):
        self._toast_host.toast(text)

    def closeEvent(self, event):
        if not self._force_quit:
            action = self._close_action
            if action == "ask":
                action = self._ask_close_action()
                if action is None:        # Esc / 关闭弹窗：留在当前页
                    event.ignore()
                    return
            if action == "tray":          # 最小化到托盘：QThread 下载在后台继续
                event.ignore()
                self.hide()
                if self._download_page.has_active_downloads():
                    self._tray.showMessage(
                        "仍在后台下载", "任务完成后可从托盘图标退出程序",
                        QSystemTrayIcon.MessageIcon.Information, 3000)
                return
            self._force_quit = True
        self._teardown()
        super().closeEvent(event)
        event.accept()

    def _teardown(self):
        self._login_page.shutdown()
        self._download_page.shutdown()
        workers = [self._course_list_worker, self._homework_worker]
        workers.extend(self._tree_workers.values())
        for w in workers:
            # 单发短任务 worker（CourseListWorker 等）没有停止接口，getattr 兜底
            stop = getattr(w, "request_stop", None)
            if w is not None and w.isRunning() and stop:
                stop()
        for w in workers:
            if w is not None and w.isRunning():
                w.wait(1500)
        for w in workers:
            if w is not None and w.isRunning():
                # 兜底：请求卡在长超时（如课程列表 30s）时强杀，避免进程退出时
                # QThread 运行中被销毁触发 qFatal 崩溃框
                w.terminate()
                w.wait(1000)
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._toast_host.setGeometry(0, 0, self.width(), self.height())
