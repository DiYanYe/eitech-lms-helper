# -*- coding: utf-8 -*-
"""下载管理页：统计卡 + 任务表（进度/状态）+ 取消（工作线程信号回传）。

任务队列（2026-09-28）：下载进行中收到新任务不中断当前任务，而是追加行排队
（状态「排队中」），当前任务结束后按入队顺序自动开始；会话失效/风控/取消全部
时清空队列（红线：风控后不得自动继续发请求）。
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.ui.icons import file_icon
from app.ui.theme import status_label
from app.ui.widgets import RoundedHeader, page_shell, stat_card


class DownloadPage(QWidget):
    tasks_changed = Signal(int)      # 进行中的任务数（导航徽标）
    session_expired = Signal()       # 下载线程转发：会话失效
    risk_stopped = Signal(str)       # 下载线程转发：命中风控

    def __init__(self, toast=None, parent=None):
        super().__init__(parent)
        self._toast = toast or (lambda s: None)
        self._worker = None
        self._queue: list = []     # 排队任务：{"files": [...], "worker": w, "start_row": int}
        self._offset = 0           # 运行中任务在表格中的行偏移（信号 row 为 worker 内部索引）
        self._active_files = 0     # 运行中任务的文件数（导航徽标用）

        lay = page_shell(
            self, "下载管理",
            "顺序下载、文件间随机限速；完成 / 跳过 / 禁止状态与真实下载器一致")

        # ---- 统计卡 ----
        grid = QHBoxLayout()
        grid.setSpacing(14)
        self._stats = {}
        for key, caption, color in (("total", "任务总数", None),
                                    ("done", "完成", "#6E6A62"),
                                    ("skip", "跳过", "#6E6A62"),
                                    ("other", "禁止 / 失败", "#92071C")):
            card, value = stat_card(caption)
            if color:
                value.setStyleSheet(f"color:{color};")
            grid.addWidget(card)
            self._stats[key] = value
        lay.addLayout(grid)

        # ---- 任务表 ----
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["文件", "大小", "状态", "进度"])
        header = RoundedHeader(self._table)
        self._table.setHorizontalHeader(header)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setIconSize(QSize(22, 22))
        lay.addWidget(self._table, 1)

        # ---- 底部提示 / 取消 ----
        bottom = QHBoxLayout()
        self._hint = QLabel("等待任务…从「资料下载」页选择文件后开始")
        self._hint.setObjectName("Muted")
        bottom.addWidget(self._hint)
        bottom.addStretch(1)
        self._cancel_btn = QPushButton("取消全部")
        self._cancel_btn.setObjectName("DangerGhost")
        self._cancel_btn.hide()
        self._cancel_btn.clicked.connect(self._cancel)
        bottom.addWidget(self._cancel_btn)
        lay.addLayout(bottom)

    # ---------- 任务装载与启动 ----------

    def start_tasks(self, files: list, worker):
        """MainWindow 构建好 DownloadWorker 后传入：忙碌则排队，空闲立即启动。"""
        if self._worker is not None and self._worker.isRunning():
            self._enqueue(files, worker)
        else:
            self._start_fresh(files, worker)

    def _start_fresh(self, files: list, worker):
        """空闲启动：清空表格（新一批）→ 填表 → 连信号 → 启动。"""
        self._queue.clear()          # 防御：正常时序下此处队列必为空
        self._worker = worker
        self._active_files = len(files)
        self._offset = 0
        self._table.setRowCount(0)
        self._table.setRowCount(len(files))
        for row, node in enumerate(files):
            self._fill_row(row, node)
        self._update_stats()
        self._emit_badge()
        self._connect(worker)
        self._cancel_btn.show()
        self._cancel_btn.setEnabled(True)
        self._hint.setText("正在下载…（顺序限速，完成后自动记录）")
        worker.start()

    def _enqueue(self, files: list, worker):
        """任务排队：表格末尾追加行（状态「排队中」），当前任务结束后自动开始。"""
        start_row = self._table.rowCount()
        self._table.setRowCount(start_row + len(files))
        for i, node in enumerate(files):
            self._fill_row(start_row + i, node)
        self._queue.append({"files": list(files), "worker": worker,
                            "start_row": start_row})
        self._update_stats()
        self._emit_badge()
        self._cancel_btn.show()
        self._cancel_btn.setEnabled(True)
        self._hint.setText(
            f"已排队 {len(self._queue)} 个任务…（当前任务完成后自动开始）")
        self._toast(f"已有下载进行中，新任务（{len(files)} 个文件）已排队")

    def _fill_row(self, row: int, node):
        name_item = QTableWidgetItem(node.relative_path)
        name_item.setIcon(file_icon(node.node_type))
        self._table.setItem(row, 0, name_item)
        self._table.setItem(row, 1, self._plain(node.size_text or "—", muted=True))
        self._table.setItem(row, 2, self._status_item("queued"))
        self._table.setCellWidget(row, 3, self._make_bar())

    def _connect(self, worker):
        worker.task_started.connect(self._on_started)
        worker.task_progress.connect(self._on_progress)
        worker.task_finished.connect(self._on_finished)
        worker.all_finished.connect(self._on_all_finished)
        worker.session_expired.connect(self._on_session_stopped)
        worker.risk_stopped.connect(self._on_risk_stopped)

    def _stop_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
        self._worker = None

    def has_active_downloads(self) -> bool:
        """是否有下载任务进行中或排队（供关闭确认弹窗提示后台继续）。"""
        return bool(self._queue) or (
            self._worker is not None and self._worker.isRunning())

    def shutdown(self):
        """窗口关闭时停止下载线程并放弃排队任务。"""
        self._queue.clear()
        self._stop_worker()

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
        self._drain_queue("已取消")
        self._cancel_btn.setEnabled(False)
        self._hint.setText("正在取消…（当前文件写完即停，排队任务一并放弃）")

    def _drain_queue(self, reason: str):
        """放弃全部排队任务：对应行状态置「已取消」。"""
        for entry in self._queue:
            for i in range(len(entry["files"])):
                self._set_status(entry["start_row"] + i, "cancelled", reason)
        self._queue.clear()

    def _emit_badge(self):
        """导航徽标 = 运行中任务文件数 + 排队任务文件数。"""
        self.tasks_changed.emit(
            self._active_files + sum(len(e["files"]) for e in self._queue))

    # ---------- 工作线程信号回调 ----------

    def _on_started(self, row: int):
        self._set_status(row + self._offset, "running")

    def _on_progress(self, row: int, percent: int):
        bar = self._table.cellWidget(row + self._offset, 3)
        bar = bar.findChild(QProgressBar) if bar else None
        if not bar:
            return
        if percent < 0:      # 服务器未返回 Content-Length：忙碌指示
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(percent)

    def _on_finished(self, row: int, status: str, detail: str):
        row += self._offset
        self._set_status(row, status, detail)
        if status in ("done", "updated"):
            wrap = self._table.cellWidget(row, 3)
            bar = wrap.findChild(QProgressBar) if wrap else None
            if bar:
                bar.setRange(0, 100)
                bar.setValue(100)
                bar.setObjectName("PBarDone")
                bar.style().unpolish(bar)
                bar.style().polish(bar)

    def _on_session_stopped(self):
        """会话失效：排队任务持有旧会话不能再跑，先放弃再转发主窗口回登录页。"""
        self._drain_queue("已取消（会话失效）")
        self.session_expired.emit()

    def _on_risk_stopped(self, message: str):
        """命中风控（红线：立即停止不硬闯）：排队任务一并放弃，不自动继续请求。"""
        self._drain_queue("已取消（命中风控）")
        self.risk_stopped.emit(message)

    def _on_all_finished(self, done: int, skipped: int, other: int):
        if self._queue:
            # 队列派发：all_finished 由 run() finally 发出，线程可能尚未完全退出，
            # 先 wait 收尾再替换引用，避免 QThread 运行中被销毁
            if self._worker is not None:
                self._worker.wait(2000)
            entry = self._queue.pop(0)
            self._worker = entry["worker"]
            self._active_files = len(entry["files"])
            self._offset = entry["start_row"]
            self._connect(self._worker)
            self._update_stats()
            self._emit_badge()
            self._cancel_btn.setEnabled(True)
            self._hint.setText("上一任务完成，开始下一任务…（顺序限速）")
            self._worker.start()
            return
        self._active_files = 0
        self._update_stats()
        done_n = int(self._stats["done"].text() or 0)
        skip_n = int(self._stats["skip"].text() or 0)
        self._cancel_btn.hide()
        self._hint.setText(
            f"本轮任务已结束：完成 {done_n} · 跳过 {skip_n} · 禁止/失败 "
            f"{int(self._stats['other'].text() or 0)}"
            f"（文件保存在「资料下载」页设置的目录）")
        self._toast(f"下载结束：完成 {done_n} · 跳过 {skip_n}")
        self.tasks_changed.emit(0)

    # ---------- 杂项 ----------

    def _make_bar(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 8, 0)
        bar = QProgressBar()
        bar.setObjectName("PBar")
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        bar.setValue(0)
        lay.addWidget(bar, 1, Qt.AlignmentFlag.AlignVCenter)
        return wrap

    def _plain(self, text: str, muted: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if muted:
            item.setForeground(QColor("#8A8378"))
        return item

    def _status_item(self, status: str) -> QTableWidgetItem:
        text, color = status_label(status)
        item = QTableWidgetItem(f"● {text}")
        item.setForeground(QColor(color))
        return item

    def _set_status(self, row: int, status: str, detail: str = ""):
        item = self._status_item(status)
        if detail:
            item.setToolTip(detail)
        self._table.setItem(row, 2, item)

    def _update_stats(self):
        # 从表格实时统计（worker 异步改状态，避免双份状态源）
        done = skip = other = 0
        total = self._table.rowCount()
        for row in range(total):
            item = self._table.item(row, 2)
            text = item.text() if item else ""
            if "完成" in text or "更新" in text:
                done += 1
            elif "跳过" in text:
                skip += 1
            elif "取消" in text or "失败" in text or "禁止" in text:
                other += 1
        self._stats["total"].setText(str(total))
        self._stats["done"].setText(str(done))
        self._stats["skip"].setText(str(skip))
        self._stats["other"].setText(str(other))
