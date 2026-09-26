# -*- coding: utf-8 -*-
"""登录引导页：真实 CAS 手动登录（DrissionPage + 真 Edge，Cookie DPAPI 加密缓存）。

未登录时它就是主界面（不常驻导航）；登录成功后自动进入资料下载。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from app.ui.workers import LoginWorker

_MUTED = QColor("#8A8378")
_INK = QColor("#241A1D")


class LoginPage(QWidget):
    login_success = Signal(object, str)      # (ChaoxingSession, 用户展示名)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self._worker = None
        self._auto = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(640)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addStretch(1)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 32, 36, 28)
        lay.setSpacing(10)

        title = QLabel("登录超星学习通（校园版）")
        title.setObjectName("PageTitle")
        lay.addWidget(title)

        hint = QLabel(
            "点击下方按钮将打开真实 Edge 浏览器，跳转学校统一身份认证（CAS）手动完成登录\n"
            "（重新登录同样会打开浏览器，不会复用本地缓存）；启动时会先用本地缓存自动尝试。\n"
            "登录成功后会话 Cookie 以 DPAPI 加密缓存，仅当前 Windows 用户可解密，失效后自动重新引导。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addSpacing(6)

        self._steps = QListWidget()
        self._steps.setObjectName("LoginSteps")
        self._steps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._steps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for i, text in enumerate(LoginWorker.STEPS):
            item = QListWidgetItem(f"{i + 1}   {text}", self._steps)
            item.setForeground(_MUTED)
        lay.addWidget(self._steps)

        self._banner = QLabel("")
        self._banner.setObjectName("Banner")
        self._banner.setWordWrap(True)
        self._banner.hide()
        lay.addWidget(self._banner)

        row = QHBoxLayout()
        row.addStretch(1)
        self._btn = QPushButton("启动浏览器登录")
        self._btn.setObjectName("Primary")
        self._btn.clicked.connect(self.start)
        row.addWidget(self._btn)
        row.addStretch(1)
        lay.addLayout(row)

    # ---------- 登录流程 ----------

    def start(self):
        self._begin(auto=False)

    def start_auto(self):
        """启动时静默尝试：仅用本地缓存自动登录，缺缓存不弹浏览器。"""
        self._begin(auto=True)

    def _begin(self, auto: bool):
        if self._worker and self._worker.isRunning():
            return
        self._auto = auto
        self._btn.setEnabled(False)
        self._btn.setText("正在自动登录…" if auto else "正在登录…")
        self._banner.hide()
        self._render_steps([""] * len(LoginWorker.STEPS))

        self._worker = LoginWorker(self, auto=auto)
        self._worker.step_changed.connect(self._on_step)
        self._worker.login_success.connect(self._on_success)
        self._worker.login_failed.connect(self._on_failed)
        self._worker.start()

    def _render_steps(self, states: list):
        for i, state in enumerate(states):
            item = self._steps.item(i)
            if state == "running":
                mark, color = "…", _INK
            elif state == "done":
                mark, color = "✔", _INK
            else:
                mark, color = str(i + 1), _MUTED
            item.setText(f"{mark}   {LoginWorker.STEPS[i]}")
            item.setForeground(color)
            font = item.font()
            font.setBold(state == "done")
            item.setFont(font)

    def _on_step(self, idx: int, state: str):
        states = [""] * len(LoginWorker.STEPS)
        # 已完成的步骤保持 done；QSS 无状态记忆，逐帧重绘最简单：
        for i in range(idx):
            states[i] = "done"
        states[idx] = state
        self._render_steps(states)

    def _on_success(self, session, display_name: str):
        self._auto = False
        self._btn.setEnabled(True)
        self._btn.setText("重新登录")
        self._banner.setText(f"登录成功：{display_name}。会话 Cookie 已加密缓存（DPAPI）。")
        self._banner.show()
        self.login_success.emit(session, display_name)

    def _on_failed(self, message: str):
        was_auto = self._auto
        self._auto = False
        self._btn.setEnabled(True)
        self._btn.setText("启动浏览器登录")
        if was_auto:
            self._banner.setText(f"自动登录未成功：{message}，请点击下方按钮手动登录")
        else:
            self._banner.setText(f"登录未完成：{message}")
        self._banner.show()

    def shutdown(self):
        """窗口关闭时停止登录线程（should_stop 会让浏览器尽快退出）。"""
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
