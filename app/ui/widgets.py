# -*- coding: utf-8 -*-
"""通用界面小部件：导航按钮（带徽标）、用户条、Toast、课程选择器、圆角表头、页面骨架、统计卡。"""
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget,
)


class RoundedHeader(QHeaderView):
    """首列左角/末列右角圆化的表头（部件级遮罩实现）。

    背景：树/表格卡片的 QSS 外圆角（14px）被方形表头盖住、左右上角被切平。
    QSS 的 QHeaderView::section:first/:last 圆角在 Qt 6 不生效；paintSection 里
    setClipPath 也会被样式引擎 drawControl 内的 ReplaceClip 重置——两者都不可靠。
    setMask 是绘制系统强制的部件级裁剪，不受 painter 裁剪重置影响。
    radius 应为卡片外圆角 − 边框宽（14 − 1 = 13），与边框内弧同心。
    """

    def __init__(self, parent=None, radius: float = 13.0):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._radius = radius

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h, r = self.width(), self.height(), self._radius
        if w <= 0 or h <= 0 or r <= 0:
            return
        path = QPainterPath()
        path.moveTo(0, h)
        path.lineTo(0, r)
        path.quadTo(0, 0, r, 0)          # 左上圆角
        path.lineTo(w - r, 0)
        path.quadTo(w, 0, w, r)          # 右上圆角
        path.lineTo(w, h)
        path.closeSubpath()
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class NavButton(QPushButton):
    """侧边导航按钮，右侧可挂红色数字徽标（对齐 Demo 的 nav-badge）。"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._badge = QLabel("0", self)
        self._badge.setObjectName("NavBadge")
        self._badge.hide()

    def set_badge(self, count: int):
        self._badge.setText(str(count))
        self._badge.setVisible(bool(count))
        self._place_badge()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_badge()

    def _place_badge(self):
        if not self._badge.isVisible():
            return
        self._badge.adjustSize()
        self._badge.move(self.width() - self._badge.width() - 12,
                         (self.height() - self._badge.height()) // 2)


class UserChip(QWidget):
    """侧边栏底部用户条（头像圈 + 名称），点击回登录页。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(9)
        self.avatar = QLabel("?")
        self.avatar.setObjectName("Avatar")
        self.avatar.setFixedSize(28, 28)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel("未登录")
        self.name.setObjectName("UserChipName")
        lay.addWidget(self.avatar)
        lay.addWidget(self.name)
        lay.addStretch(1)

    def set_user(self, display: str):
        self.avatar.setText(display[0] if display else "?")
        self.name.setText(display)

    def mousePressEvent(self, event):
        self.clicked.emit()


class ElidedLabel(QLabel):
    """超长文本中间省略（用于下载目录展示），tooltip 保留完整路径。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""

    def set_full_text(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if not self._full:
            self.setText("")
            return
        fm = self.fontMetrics()
        width = max(self.width() - 2, 40)
        self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideMiddle, width))


class ToastHost(QWidget):
    """右上角轻提示堆叠（对齐 Demo 的 toast）。不拦截鼠标事件。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._labels: list = []

    def toast(self, text: str):
        lb = QLabel(text, self)
        lb.setObjectName("Toast")
        lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lb.adjustSize()
        lb.show()
        self._labels.append(lb)
        self._reposition()
        QTimer.singleShot(2600, lambda: self._drop(lb))

    def _drop(self, lb: QLabel):
        if lb in self._labels:
            self._labels.remove(lb)
            lb.deleteLater()
            self._reposition()

    def _reposition(self):
        x = self.width() - 24
        y = 22
        for lb in reversed(self._labels):
            lb.move(x - lb.width(), y)
            y += lb.height() + 9


class CoursePicker(QPushButton):
    """课程选择器：按钮 + 圆角菜单（替代原生 QComboBox 下拉，风格与整体一致）。"""

    picked = Signal(int)              # 选中的课程序号
    manage_requested = Signal()       # 菜单底部“管理课程…”被点击

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._items: list = []
        self._index = -1
        self.clicked.connect(self.show_menu)
        self._sync_text()

    def set_items(self, items: list, index: int = 0):
        self._items = list(items)
        self.set_index(index)

    def set_index(self, index: int):
        self._index = index
        self._sync_text()

    def current_index(self) -> int:
        return self._index

    def _sync_text(self):
        if 0 <= self._index < len(self._items):
            self.setText(f"{self._items[self._index]}   ▾")
        else:
            self.setText("选择课程   ▾")

    def show_menu(self):
        menu = QMenu(self)
        menu.setObjectName("CourseMenu")
        # 圆角菜单去黑角三件套：无边框 + 去掉 DWM 方形投影 + 半透明背景
        menu.setWindowFlags(menu.windowFlags()
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setMinimumWidth(max(self.width(), 200))
        for i, label in enumerate(self._items):
            current = i == self._index
            act = menu.addAction(f"✓  {label}" if current else f"　  {label}")
            act.setData(i)
            if current:
                font = act.font()
                font.setBold(True)
                act.setFont(font)
        if self._items:
            menu.addSeparator()
        manage_act = menu.addAction("⚙  管理课程…")
        chosen = menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
        if chosen is None:
            return
        if chosen is manage_act:
            self.manage_requested.emit()
            return
        i = int(chosen.data())
        if i != self._index:
            self.set_index(i)
            self.picked.emit(i)


def page_shell(widget: QWidget, title: str, hint: str, max_width: int = 1080) -> QVBoxLayout:
    """Demo 版式的页面骨架：限宽居中内容 + 标题 + 灰色说明。返回内容布局。

    两侧 addStretch() 必须是 stretch 0：窄窗口时内容（stretch 1）铺满可用宽度，
    宽窗口时内容到 max_width 上限后剩余空间由两侧均分（居中）。
    """
    widget.setObjectName("Page")
    outer = QHBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addStretch()
    content = QWidget()
    content.setMaximumWidth(max_width)
    lay = QVBoxLayout(content)
    lay.setContentsMargins(28, 24, 28, 28)
    lay.setSpacing(12)
    outer.addWidget(content, 1)
    outer.addStretch()

    title_lb = QLabel(title)
    title_lb.setObjectName("PageTitle")
    hint_lb = QLabel(hint)
    hint_lb.setObjectName("Muted")
    hint_lb.setWordWrap(True)
    lay.addWidget(title_lb)
    lay.addWidget(hint_lb)
    return lay


def stat_card(caption: str) -> tuple:
    """统计小卡（大数字 + 灰色说明）。返回 (frame, value_label)。"""
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(2)
    value = QLabel("0")
    value.setObjectName("StatValue")
    cap = QLabel(caption)
    cap.setObjectName("Muted")
    lay.addWidget(value)
    lay.addWidget(cap)
    return frame, value
