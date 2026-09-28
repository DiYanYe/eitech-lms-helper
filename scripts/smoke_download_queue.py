# -*- coding: utf-8 -*-
"""下载队列冒烟：忙碌中发起新任务排队、完成后自动接续、取消全部清队列。

不碰网络：FakeWorker(QThread) 用 time.sleep + 信号模拟下载时序。
运行（eitech-lms 环境，offscreen 平台）：
  $env:PYTHONDONTWRITEBYTECODE='1'
  C:/Users/DIYAN/scoop/persist/miniconda3/envs/eitech-lms/python.exe scripts/smoke_download_queue.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.pages.download_page import DownloadPage  # noqa: E402

CHECKS = []


def check(name: str, ok: bool):
    CHECKS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}", flush=True)


def wait_until(cond, timeout_ms: int = 5000):
    """处理事件循环直到 cond 为真（信号跨线程为排队投递，必须转事件循环）。"""
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(15)
    timer.timeout.connect(lambda: cond() and loop.quit())
    timer.start()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()


class FakeNode:
    def __init__(self, rel: str):
        self.relative_path = rel
        self.size_text = "1 MB"
        self.node_type = "doc"


class FakeWorker(QThread):
    task_started = Signal(int)
    task_progress = Signal(int, int)
    task_finished = Signal(int, str, str)
    all_finished = Signal(int, int, int)
    session_expired = Signal()
    risk_stopped = Signal(str)

    def __init__(self, files, ms_per_file: int = 80):
        super().__init__()
        self._files = list(files)
        self._ms = ms_per_file
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True

    def run(self):
        for i in range(len(self._files)):
            if self.stop_requested:
                self.task_finished.emit(i, "cancelled", "已中止")
                continue
            self.task_started.emit(i)
            self.task_progress.emit(i, 100)
            time.sleep(self._ms / 1000)
            self.task_finished.emit(i, "done", "")
        self.all_finished.emit(len(self._files), 0, 0)


def row_status(page, row: int) -> str:
    item = page._table.item(row, 2)
    return item.text() if item else ""


def main():
    app = QApplication(sys.argv)
    page = DownloadPage()
    badges: list = []
    page.tasks_changed.connect(badges.append)

    # ---- 场景 1：A 下载中入队 B → A 完成后 B 自动接续 ----
    files_a = [FakeNode("A/1.pdf"), FakeNode("A/2.pdf")]
    files_b = [FakeNode("B/1.doc"), FakeNode("B/2.doc"), FakeNode("B/3.doc")]
    wa = FakeWorker(files_a, ms_per_file=80)
    page.start_tasks(files_a, wa)
    check("A 立即启动：表格 2 行", page._table.rowCount() == 2)
    check("A 启动后 has_active=True", page.has_active_downloads())

    wb = FakeWorker(files_b, ms_per_file=60)
    page.start_tasks(files_b, wb)   # A 运行中 → 应入队而非打断
    check("B 入队：表格追加为 5 行", page._table.rowCount() == 5)
    check("B 行状态「排队中」", "排队中" in row_status(page, 2))
    check("B 未被启动（排队等候）", not wb.isRunning())
    check("B 入队不触碰 A（未 request_stop）", not wa.stop_requested)
    check("徽标 = 2+3", badges and badges[-1] == 5)

    wait_until(lambda: wb.isRunning() and "下载中" in row_status(page, 2))
    check("A 完成后 B 自动开始（B 首行「下载中」）",
          wb.isRunning() and "下载中" in row_status(page, 2))
    wait_until(lambda: not page.has_active_downloads())
    check("B 完成后全部结束", not page.has_active_downloads())
    check("A 全程未被中断", not wa.stop_requested)
    check("行保留为会话历史（仍 5 行）", page._table.rowCount() == 5)
    check("结束：取消按钮隐藏", page._cancel_btn.isHidden())
    check("结束：徽标归零", badges[-1] == 0)
    check("结束 hint 汇总", "本轮任务已结束" in page._hint.text())
    check("徽标序列 [A,入队B,派发B,0]", badges == [2, 5, 3, 0])

    # ---- 场景 2：C 下载中入队 D → 取消全部 → D 放弃且永不启动 ----
    files_c = [FakeNode("C/1.pdf"), FakeNode("C/2.pdf"), FakeNode("C/3.pdf")]
    files_d = [FakeNode("D/1.pdf")]
    wc = FakeWorker(files_c, ms_per_file=150)
    page.start_tasks(files_c, wc)
    check("C 空闲启动：表格清空重填 3 行", page._table.rowCount() == 3)
    wd = FakeWorker(files_d, ms_per_file=50)
    page.start_tasks(files_d, wd)
    check("D 入队：4 行", page._table.rowCount() == 4)
    check("D 行「排队中」", "排队中" in row_status(page, 3))
    page._cancel()   # 取消全部：停止 C + 放弃 D
    check("取消全部：D 行「已取消」", "已取消" in row_status(page, 3))
    check("取消全部：队列清空", page._queue == [])
    wait_until(lambda: not page.has_active_downloads())
    check("C 停止后收尾，D 从未启动", not wd.isRunning() and wd.stop_requested is False)
    check("收尾：徽标归零", badges[-1] == 0)
    check("徽标序列 [C,入队D,0]", badges[len(badges) - 3:] == [3, 4, 0])

    # ---- 汇总 ----
    sys.stdout.flush()
    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n===== 冒烟结果：{len(CHECKS) - len(failed)}/{len(CHECKS)} PASS =====",
          flush=True)
    if failed:
        for n in failed:
            print(f"  FAIL: {n}", flush=True)
        os._exit(1)
    os._exit(0)   # offscreen 退出伪像兜底（AGENTS.md）


if __name__ == "__main__":
    main()
