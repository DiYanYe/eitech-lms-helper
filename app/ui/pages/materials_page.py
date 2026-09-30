# -*- coding: utf-8 -*-
"""资料下载页：课程选择 + 全选 + 浏览器打开 + 自定义下载目录 + 资料树勾选。

交互（对齐 docs/ui-demo.html）：
- 点击文件所在行任意位置即可勾选/取消；点击文件夹一次全选/清空其下文件
- 勾选状态以 self._checked（叶子 data_id 集合）为唯一状态源，树控件仅作视觉呈现
"""
import os
from datetime import datetime

from PySide6.QtCore import Qt, QSettings, QSize, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app import config
from app.core.api.courses import course_key, material_page_url
from app.ui.icons import file_icon
from app.ui.widgets import CoursePicker, ElidedLabel, RoundedHeader, page_shell
from app.utils import parse_size_text

DEFAULT_DIR = str(config.DOWNLOAD_ROOT)


def _fmt_time(node) -> str:
    """资料行上传时间展示文本：平台原文（规范化空白）→ remote_mtime 格式化兜底 → 空。"""
    text = " ".join((node.remote_time_text or "").split())
    if text:
        return text
    if node.remote_mtime:
        return datetime.fromtimestamp(node.remote_mtime).strftime("%m-%d %H:%M")
    return ""


class CheckTree(QTreeWidget):
    """接管鼠标点击的资料树：行内点击 → node_clicked 信号，避免原生勾选二次切换。

    展开箭头区域仍交给原生行为（折叠/展开）；禁用行同样交还原生。
    """

    node_clicked = Signal(object, object)    # (MaterialNode, QTreeWidgetItem)

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        item = self.itemAt(pos)
        if item is None:
            super().mouseReleaseEvent(e)
            return
        # visualItemRect 已排除该项左侧的分支箭头槽（vis.x = (depth+1)*缩进）：
        # 箭头区 = vis.x 左侧 → 原生折叠/展开；其余（复选框/整行）→ 我们的统一切换
        if pos.x() < self.visualItemRect(item).x():
            super().mouseReleaseEvent(e)
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            super().mouseReleaseEvent(e)
            return
        # 不调 super：防止原生 checkbox toggle 造成二次状态变化
        self.node_clicked.emit(node, item)


class MaterialsPage(QWidget):
    download_requested = Signal(list)    # list[MaterialNode]（勾选的文件节点）
    course_selected = Signal(object)     # Course（picker 变化 / 默认首课；触发按需拉树）
    manage_requested = Signal()          # ⚙ 管理课程（CoursePicker 菜单转发）

    def __init__(self, toast=None, parent=None):
        super().__init__(parent)
        self._toast = toast or (lambda s: None)
        self._courses = []               # 当前已选课程（仅这些会发起请求）
        self._roots: dict = {}           # course_key -> roots（缺省 None = 未加载）
        self._errors: dict = {}          # course_key -> 最近一次加载失败原因
        self._loading: set = set()       # 正在拉取资料树的 course_key
        self._course_index = 0
        self._checked: set = set()       # 勾选叶子 data_id（跨课程共享，唯一状态源）
        self._disabled: set = set()      # 不可勾选节点 data_id
        self._settings = QSettings("eitech", "lms-helper")
        self.download_dir = self._settings.value("download/dir", DEFAULT_DIR)

        lay = page_shell(
            self, "资料下载",
            "点击文件所在行即可勾选/取消，点击文件夹一次全选/清空其下文件；"
            "教师课件与未开放下载项不可选（平台权限，助手不会强行获取）")

        # ---- 工具栏：课程 / 全选 / 浏览器打开 / 下载目录 ----
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self._picker = CoursePicker()
        self._picker.picked.connect(self._on_course_changed)
        self._picker.manage_requested.connect(self.manage_requested.emit)
        bar.addWidget(self._picker)

        self._sel_all_btn = QPushButton("全选")
        self._sel_all_btn.setObjectName("Ghost")
        self._sel_all_btn.clicked.connect(self.select_all)
        bar.addWidget(self._sel_all_btn)

        self._refresh_btn = QPushButton("⟳  刷新")
        self._refresh_btn.setObjectName("Ghost")
        self._refresh_btn.setToolTip("重新拉取当前课程的资料树")
        self._refresh_btn.clicked.connect(self._refresh_current)
        bar.addWidget(self._refresh_btn)

        browse_btn = QPushButton("🌐 浏览器打开")
        browse_btn.setObjectName("Ghost")
        browse_btn.setToolTip("在系统浏览器中打开当前课程的资料页")
        browse_btn.clicked.connect(self._open_in_browser)
        bar.addWidget(browse_btn)

        divider = QFrame()
        divider.setObjectName("VLine")
        divider.setFixedSize(1, 22)
        bar.addWidget(divider)

        dir_box = QFrame()
        dir_box.setObjectName("DirBox")
        dir_box.setMinimumWidth(280)
        dir_lay = QHBoxLayout(dir_box)
        dir_lay.setContentsMargins(12, 6, 6, 6)
        dir_lay.setSpacing(8)
        dir_label = QLabel("下载到")
        dir_label.setObjectName("Muted")
        dir_lay.addWidget(dir_label)
        self._dir_path = ElidedLabel()
        self._dir_path.setObjectName("DirPath")
        dir_lay.addWidget(self._dir_path, 1)
        change_btn = QPushButton("更改")
        change_btn.setObjectName("Ghost")
        change_btn.setToolTip("弹出系统目录选择对话框")
        change_btn.clicked.connect(self._pick_dir)
        dir_lay.addWidget(change_btn)
        open_btn = QPushButton("打开")
        open_btn.setObjectName("Ghost")
        open_btn.setToolTip("在系统资源管理器中打开当前下载目录")
        open_btn.clicked.connect(self._open_dir)
        dir_lay.addWidget(open_btn)
        bar.addWidget(dir_box, 1)
        lay.addLayout(bar)

        # ---- 资料树 ----
        self._tree = CheckTree()
        self._tree.setObjectName("MatTree")   # theme.py 按名注入数据列左右留白
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["文件", "大小", "上传时间", "说明"])
        self._tree.setHeader(RoundedHeader(self._tree))
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setIconSize(QSize(22, 22))
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self._tree.setFrameShape(QFrame.NoFrame)
        self._tree.node_clicked.connect(self._on_node_clicked)
        lay.addWidget(self._tree, 1)
        # ---- 底部结算栏 ----
        foot = QFrame()
        foot.setObjectName("Card")
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(20, 14, 20, 14)
        foot_lay.setSpacing(12)
        self._sum = QLabel("已选 <b>0</b> 个文件")
        self._sum.setTextFormat(Qt.TextFormat.RichText)
        foot_lay.addWidget(self._sum)
        self._size_hint = QLabel("")
        self._size_hint.setObjectName("Muted")
        foot_lay.addWidget(self._size_hint)
        foot_lay.addStretch(1)
        self._dl_btn = QPushButton("开始下载 →")
        self._dl_btn.setObjectName("Primary")
        self._dl_btn.setEnabled(False)
        self._dl_btn.clicked.connect(self._emit_download)
        foot_lay.addWidget(self._dl_btn)
        lay.addWidget(foot)

        self._update_dir_ui()
        self._load_tree()   # 初始空态：显示“尚未选择课程”引导行

    # ---------- 数据装载 ----------

    def set_courses(self, courses: list):
        """courses: list[Course]（已选课程）。已加载的课程树按 course_key 保留。"""
        new_keys = {course_key(c) for c in courses}
        for c in self._courses:
            k = course_key(c)
            if k not in new_keys:
                self._purge(k)
        self._courses = list(courses)
        self._course_index = 0
        self._picker.set_items([c.name for c in self._courses])
        self._load_tree()
        if self._courses:
            self.course_selected.emit(self._courses[0])

    def set_course_roots(self, key: str, roots: list, error: str = ""):
        """TreeWorker 结果回填；key 已不在当前课程列表（被移除）时丢弃。"""
        self._loading.discard(key)
        if key not in {course_key(c) for c in self._courses}:
            return
        if error:
            self._errors[key] = error
            self._roots.pop(key, None)
        else:
            self._errors.pop(key, None)
            self._roots[key] = list(roots)
            self._build_state(self._roots[key])
        course = self._current_course()
        if course is not None and course_key(course) == key:
            self._load_tree()

    def begin_load_if_needed(self, course) -> bool:
        """课程树未加载且不在加载中 → 标记加载并切到占位视图，返回 True。

        MainWindow 据返回值决定是否启动 TreeWorker（未选课程零请求的闸门）。
        """
        key = course_key(course)
        if self._roots.get(key) is not None or key in self._loading:
            return False
        self._loading.add(key)
        self._errors.pop(key, None)   # 允许失败重试
        self._load_tree()
        return True

    def current_course(self):
        return self._current_course()

    def _refresh_current(self):
        """丢弃当前课程资料树缓存并重新拉取（course_selected → MainWindow 起 TreeWorker）。"""
        course = self._current_course()
        if course is None:
            return
        key = course_key(course)
        if key in self._loading:
            self._toast("资料列表正在加载中，请稍候")
            return
        self._purge(key)
        self.course_selected.emit(course)

    def _purge(self, key: str):
        """移除课程的全部本地缓存与勾选状态（不再发起任何请求）。"""
        roots = self._roots.pop(key, None)
        if roots:
            def visit(nd):
                self._checked.discard(nd.data_id)
                self._disabled.discard(nd.data_id)
            self._walk_nodes(roots, visit)
        self._errors.pop(key, None)
        self._loading.discard(key)

    def _build_state(self, roots: list):
        """登记禁用项；可勾选叶子默认全选（树到位时逐课程执行）。"""
        def visit(nd):
            if self._is_disabled(nd):
                self._disabled.add(nd.data_id)
            elif not nd.children:
                self._checked.add(nd.data_id)
        self._walk_nodes(roots, visit)

    def _walk_nodes(self, nodes, fn):
        for nd in nodes:
            fn(nd)
            if nd.children:
                self._walk_nodes(nd.children, fn)

    def _is_disabled(self, nd) -> bool:
        return nd.special or not nd.is_down

    def _current_course(self):
        if 0 <= self._course_index < len(self._courses):
            return self._courses[self._course_index]
        return None

    def _current_roots(self) -> list:
        course = self._current_course()
        if course is None:
            return []
        roots = self._roots.get(course_key(course))
        return roots if roots else []

    def _on_course_changed(self, index: int):
        self._course_index = index
        self._load_tree()
        course = self._current_course()
        if course is not None:
            self.course_selected.emit(course)

    def _load_tree(self):
        self._tree.clear()
        course = self._current_course()
        if course is None:
            item = QTreeWidgetItem(["尚未选择课程", "", "", "点击课程框 → ⚙ 管理课程 添加关注课程"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.invisibleRootItem().addChild(item)
        else:
            roots = self._roots.get(course_key(course))
            if roots is None:
                err = self._errors.get(course_key(course))
                text = (f"资料列表加载失败：{err}（重新选择该课程可重试）"
                        if err else "正在加载资料列表…")
                item = QTreeWidgetItem([text, "", "", ""])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self._tree.invisibleRootItem().addChild(item)
            else:
                for nd in roots:
                    self._add_node(None, nd)
        self._tree.expandAll()
        self._update_summary()

    def _add_node(self, parent_item, node):
        prefix = ""
        icon = None
        note = ""
        checkable = True
        if node.node_type == "afolder":
            prefix = "📁 "
            note = f"{len(node.children)} 项" if node.children else "空文件夹"
        elif node.special:
            prefix = "🔒 "
            note = "教师课件 · 仅展示（不下载）"
            checkable = False
        elif not node.is_down:
            note = "教师未开放下载"
            checkable = False
        else:
            icon = file_icon(node.node_type)
            note = node.node_type.upper()

        item = QTreeWidgetItem([f"{prefix}{node.name}", node.size_text, _fmt_time(node), note])
        # 数据三列居中：表头默认就是 AlignHCenter|AlignVCenter，条目跟随同轴对齐
        center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        for col in (1, 2, 3):
            item.setTextAlignment(col, center)
        if icon is not None:
            item.setIcon(0, icon)
        if checkable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, self._state_of(node))
        else:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        (parent_item or self._tree.invisibleRootItem()).addChild(item)
        for child in node.children:
            self._add_node(item, child)
        return item

    # ---------- 勾选状态（唯一状态源：self._checked） ----------

    def _state_of(self, node) -> Qt.CheckState:
        if not node.children:
            return (Qt.CheckState.Checked if node.data_id in self._checked
                    else Qt.CheckState.Unchecked)
        states = [self._state_of(ch) for ch in node.children]
        if states and all(s == Qt.CheckState.Checked for s in states):
            return Qt.CheckState.Checked
        if states and all(s == Qt.CheckState.Unchecked for s in states):
            return Qt.CheckState.Unchecked
        return Qt.CheckState.PartiallyChecked

    def _set_leaf(self, node, on: bool):
        if on:
            self._checked.add(node.data_id)
        else:
            self._checked.discard(node.data_id)

    def _on_node_clicked(self, node, item):
        """行/复选框点击：非全选状态一律切换为全选（对齐 Demo）。"""
        if self._is_disabled(node):
            return
        on = item.checkState(0) != Qt.CheckState.Checked
        self._apply_toggle(node, item, on)

    def _apply_toggle(self, node, item, on: bool):
        self._apply_recursive(node, item, on)
        p = item.parent()          # 自下而上刷新祖先三态
        while p is not None:
            pn = p.data(0, Qt.ItemDataRole.UserRole)
            p.setCheckState(0, self._state_of(pn))
            p = p.parent()
        self._update_summary()

    def _apply_recursive(self, node, item, on: bool):
        if node.children:
            for i, ch in enumerate(node.children):
                self._apply_recursive(ch, item.child(i), on)
            item.setCheckState(0, self._state_of(node))
        else:
            self._set_leaf(node, on)
            item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _checked_files(self) -> list:
        files: list = []

        def collect(nd):
            if not nd.children and nd.data_id in self._checked and not self._is_disabled(nd):
                files.append(nd)
        self._walk_nodes(self._current_roots(), collect)
        return files

    def _all_selected(self) -> bool:
        any_sel, all_sel = False, True

        def visit(nd):
            nonlocal any_sel, all_sel
            if not nd.children and not self._is_disabled(nd):
                any_sel = True
                if nd.data_id not in self._checked:
                    all_sel = False
        self._walk_nodes(self._current_roots(), visit)
        return any_sel and all_sel

    def _update_summary(self):
        files = self._checked_files()
        total = sum(parse_size_text(nd.size_text) or 0 for nd in files)
        self._sum.setText(
            f"已选 <b style='color:#92071C;font-size:15px'>{len(files)}</b> 个文件")
        self._size_hint.setText(
            f"约 {self._fmt(total)}（大小为平台展示约数）" if files else "")
        self._dl_btn.setEnabled(bool(files))
        self._sel_all_btn.setText("取消全选" if self._all_selected() else "全选")

    @staticmethod
    def _fmt(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}GB"

    # ---------- 全选 / 浏览器 / 下载目录 ----------

    def select_all(self):
        on = not self._all_selected()

        def visit(nd):
            if not nd.children and not self._is_disabled(nd):
                self._set_leaf(nd, on)
        self._walk_nodes(self._current_roots(), visit)
        self._load_tree()
        self._toast("已全选当前课程可下载文件" if on else "已取消全选")

    def _open_in_browser(self):
        course = self._current_course()
        if course is None:
            return
        QDesktopServices.openUrl(QUrl(material_page_url(course)))
        self._toast(f"已在系统浏览器打开「{course.name}」资料页")

    def _update_dir_ui(self):
        self._dir_path.set_full_text(self.download_dir)

    def _pick_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "选择下载目录", self.download_dir)
        if not chosen:
            return
        self.download_dir = chosen
        self._settings.setValue("download/dir", chosen)
        self._update_dir_ui()
        self._toast("下载目录已更新，后续下载将保存到该目录")

    def _open_dir(self):
        os.makedirs(self.download_dir, exist_ok=True)    # 目录可能尚未创建（还没下载过）
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.download_dir))
        self._toast("已在资源管理器中打开下载目录")

    def _emit_download(self):
        files = self._checked_files()
        if files:
            self.download_requested.emit(files)
