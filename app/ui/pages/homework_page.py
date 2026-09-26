# -*- coding: utf-8 -*-
"""作业列表页：全部课程作业汇总，按状态分组（未交置顶），双击行在系统浏览器打开作业页。"""
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.ui.theme import status_label
from app.ui.widgets import RoundedHeader, page_shell

# 分组优先级：未完成（未交）置顶 → 等待中 → 无需动作；平台新状态归入“其他”组殿后
_GROUP_ORDER = {"未交": 0, "待批阅": 1, "已提交": 2}
_GROUP_TINT = {"未交": (146, 7, 28, 16), "待批阅": (253, 184, 55, 36)}  # QColor(r,g,b,a)


class HomeworkPage(QWidget):
    counts_changed = Signal(int)          # 未交作业数（导航徽标）
    refresh_requested = Signal()          # 手动刷新：重新拉取全部已选课程作业

    def __init__(self, toast=None, parent=None):
        super().__init__(parent)
        self._toast = toast or (lambda s: None)
        self._rows: list = []        # 行映射：item=(course_name, Homework)；分组头=None
        self._header_rows: list = [] # 跨列分组头行号（重建前先解除 span）

        lay = page_shell(
            self, "作业列表",
            "按状态分组：未交作业置顶，其余按“等待中 → 无需动作 → 其他”排列；"
            "双击任意作业直接在浏览器中打开作业页面"
            "（红=需立即行动，琥珀=等待中，灰=无需动作）")

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["课程", "作业", "状态", "时间"])
        header = RoundedHeader(self._table)
        self._table.setHorizontalHeader(header)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self._table, 1)

        self._summary = QLabel("")
        self._summary.setObjectName("Muted")
        lay.addWidget(self._summary)

        # ---- 工具行：右侧刷新按钮 ----
        bar = QHBoxLayout()
        bar.addStretch(1)
        self._refresh_btn = QPushButton("⟳  刷新")
        self._refresh_btn.setObjectName("Ghost")
        self._refresh_btn.setToolTip("重新拉取全部已选课程的作业列表")
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        bar.addWidget(self._refresh_btn)
        lay.insertLayout(2, bar)   # 标题/说明之后、表格之前

    # ---------- 刷新状态 ----------

    def set_refreshing(self, on: bool):
        self._refresh_btn.setEnabled(not on)
        self._refresh_btn.setText("正在刷新…" if on else "⟳  刷新")

    # ---------- 数据 ----------

    def set_data(self, data: dict):
        """data: course_name -> list[Homework]；按状态分组渲染，未交组置顶。"""
        for r in self._header_rows:          # 解除旧 span，避免重建后错位
            self._table.setSpan(r, 0, 1, 1)
        self._header_rows = []

        groups: dict = {}
        for cn, hws in data.items():
            for hw in hws:
                groups.setdefault(hw.status or "其他", []).append((cn, hw))
        ordered = sorted(groups.items(),
                         key=lambda kv: (_GROUP_ORDER.get(kv[0], 99), kv[0]))

        flat: list = []                      # ("header", status, count) / ("item", cn, hw)
        for status, items in ordered:
            flat.append(("header", status, len(items)))
            flat.extend(("item", cn, hw) for cn, hw in items)

        self._rows = [None if e[0] == "header" else (e[1], e[2]) for e in flat]
        self._table.setRowCount(len(flat))
        for row, e in enumerate(flat):
            if e[0] == "header":
                self._make_group_header(row, e[1], e[2])
            else:
                self._make_item_row(row, e[1], e[2])

        pending = sum(1 for r in self._rows if r and r[1].status == "未交")
        reviewing = sum(1 for r in self._rows if r and r[1].status == "待批阅")
        self._summary.setText(
            f"共 {len(self._rows) - len(self._header_rows)} 项作业 · 未交 {pending} · 待批阅 {reviewing}。"
            f"提示：双击行在浏览器中打开")
        self.counts_changed.emit(pending)

    def _make_group_header(self, row: int, status: str, count: int):
        text, color = status_label(status)
        item = QTableWidgetItem(f"●  {text} · {count} 项")
        item.setForeground(QColor(color))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        tint = _GROUP_TINT.get(status)
        if tint:
            item.setBackground(QColor(*tint))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)   # 禁选禁双击（hover 也不高亮）
        self._table.setItem(row, 0, item)
        self._table.setSpan(row, 0, 1, 4)
        self._header_rows.append(row)

    def _make_item_row(self, row: int, course_name: str, hw):
        course_item = QTableWidgetItem(course_name)
        course_item.setForeground(QColor("#8A8378"))
        self._table.setItem(row, 0, course_item)
        self._table.setItem(row, 1, QTableWidgetItem(hw.title))
        text, color = status_label(hw.status)
        status_item = QTableWidgetItem(f"● {text}")
        status_item.setForeground(QColor(color))
        self._table.setItem(row, 2, status_item)
        time_item = QTableWidgetItem(hw.time_text)
        time_item.setForeground(QColor("#8A8378"))
        self._table.setItem(row, 3, time_item)

    # ---------- 交互 ----------

    def _on_double_click(self, item):
        row = item.row()
        if row < 0 or row >= len(self._rows):
            return
        entry = self._rows[row]
        if entry is None:                    # 分组头
            return
        course_name, hw = entry
        QDesktopServices.openUrl(QUrl(hw.task_url))
        self._toast(f"已在系统浏览器打开作业「{hw.title}」")
