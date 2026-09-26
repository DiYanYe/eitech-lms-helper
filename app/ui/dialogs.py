# -*- coding: utf-8 -*-
"""课程管理对话框：勾选需要关注的课程（QSettings 持久化于 MainWindow 侧）。

仅已勾选课程会产生网络请求（作业自动拉取、资料树按需加载）；
未勾选课程自始至终零请求。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from app.core.api.courses import course_key


class CourseManageDialog(QDialog):
    """全量课程复选清单；exec() 返回 Accepted 后经 selected_keys() 取结果。"""

    def __init__(self, courses: list, selected_keys: set, parent=None):
        super().__init__(parent)
        self.setObjectName("CourseManager")
        self.setWindowTitle("管理课程")
        self.setMinimumSize(480, 540)
        self._keys = [course_key(c) for c in courses]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(10)

        title = QLabel("选择需要关注的课程")
        title.setObjectName("PageTitle")
        lay.addWidget(title)

        hint = QLabel(
            "仅勾选的课程会发起网络请求：作业每次启动自动拉取，资料树在选中课程时加载。\n"
            "取消勾选将清除该课程的本地缓存，之后不再产生任何请求。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._list = QListWidget()
        self._list.setObjectName("CourseList")
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for c in courses:
            item = QListWidgetItem(c.name, self._list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if course_key(c) in selected_keys
                else Qt.CheckState.Unchecked)
        lay.addWidget(self._list, 1)

        row = QHBoxLayout()
        self._count = QLabel("")
        self._count.setObjectName("Muted")
        row.addWidget(self._count)
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = QPushButton("保存")
        save.setObjectName("Primary")
        save.clicked.connect(self.accept)
        row.addWidget(save)
        lay.addLayout(row)

        self._list.itemChanged.connect(lambda _: self._sync_count())
        self._sync_count()

    def _sync_count(self):
        n = sum(1 for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked)
        self._count.setText(f"已选 {n} 门课程")

    def selected_keys(self) -> set:
        return {self._keys[i] for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked}


class CloseConfirmDialog(QDialog):
    """点击 × 时的关闭确认：最小化到系统托盘 / 完全退出（可记住选择）。

    exec() 接受后经 choice 取结果（"tray" / "exit"）；reject（Esc）不设 choice。
    """

    def __init__(self, downloading: bool, tray_available: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("CloseAsk")
        self.setWindowTitle("关闭窗口")
        self.setMinimumWidth(430)
        self.choice: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(10)

        title = QLabel("关闭窗口")
        title.setObjectName("PageTitle")
        lay.addWidget(title)

        text = "可以将程序最小化到系统托盘在后台继续运行，也可以完全退出程序。"
        if downloading:
            text += "\n当前有下载任务进行中，最小化到托盘后下载将继续。"
        body = QLabel(text)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        lay.addWidget(body)

        self._remember = QCheckBox("记住我的选择，以后不再询问")
        lay.addWidget(self._remember)
        lay.addSpacing(6)

        row = QHBoxLayout()
        row.addStretch(1)
        exit_btn = QPushButton("完全退出")
        exit_btn.setObjectName("Ghost")
        exit_btn.clicked.connect(lambda: self._done("exit"))
        row.addWidget(exit_btn)
        tray_btn = QPushButton("最小化到托盘")
        tray_btn.setObjectName("Primary")
        tray_btn.setDefault(True)
        tray_btn.clicked.connect(lambda: self._done("tray"))
        row.addWidget(tray_btn)
        if not tray_available:
            tray_btn.hide()
        lay.addLayout(row)

    def _done(self, choice: str):
        self.choice = choice
        self.accept()

    def remember(self) -> bool:
        return self._remember.isChecked()
