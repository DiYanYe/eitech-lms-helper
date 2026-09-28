# -*- coding: utf-8 -*-
"""下载管理页：统计卡 + 任务表（进度条/状态）+ 取消（工作线程信号回传）。"""
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
        self._files = []

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
        """MainWindow 构建好 DownloadWorker 后传入：填表 → 连信号 → 启动。"""
        self._stop_worker()
        self._files = list(files)
        self._worker = worker
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._files))
        for row, node in enumerate(self._files):
            name_item = QTableWidgetItem(node.relative_path)
            name_item.setIcon(file_icon(node.node_type))
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, self._plain(node.size_text or "—", muted=True))
            self._table.setItem(row, 2, self._status_item("queued"))
            self._table.setCellWidget(row, 3, self._make_bar())
        self._update_stats()
        self.tasks_changed.emit(len(self._files))
        self._worker.task_started.connect(self._on_started)
        self._worker.task_progress.connect(self._on_progress)
        self._worker.task_finished.connect(self._on_finished)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.session_expired.connect(self.session_expired.emit)
        self._worker.risk_stopped.connect(self.risk_stopped.emit)
        self._cancel_btn.show()
        self._cancel_btn.setEnabled(True)
        self._hint.setText("正在下载…（顺序限速，完成后自动记录）")
        self._worker.start()

    def _stop_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
        self._worker = None

    def has_active_downloads(self) -> bool:
        """是否有下载任务进行中（供关闭确认弹窗提示后台继续）。"""
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self):
        """窗口关闭时停止下载线程。"""
        self._stop_worker()

    def _cancel(self):
        if self._worker:
            self._worker.request_stop()
            self._cancel_btn.setEnabled(False)
            self._hint.setText("正在取消…（当前文件写完即停）")

    # ---------- 工作线程信号回调 ----------

    def _on_started(self, row: int):
        self._set_status(row, "running")

    def _on_progress(self, row: int, percent: int):
        bar = self._table.cellWidget(row, 3)
        bar = bar.findChild(QProgressBar) if bar else None
        if not bar:
            return
        if percent < 0:      # 服务器未返回 Content-Length：忙碌指示
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(percent)

    def _on_finished(self, row: int, status: str, detail: str):
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

    def _on_all_finished(self, done: int, skipped: int, other: int):
        self._update_stats()
        self._cancel_btn.hide()
        self._hint.setText(
            f"本轮任务已结束：完成 {done} · 跳过 {skipped} · 禁止/失败 {other}"
            f"（文件保存在「资料下载」页设置的目录）")
        self._toast(f"下载结束：完成 {done} · 跳过 {skipped}")
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
