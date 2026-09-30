# -*- coding: utf-8 -*-
"""界面主题：VI 配色（标准色 #92071C，辅助 #FDB837 / #AAA9A1）+ 全局 QSS。

三色语义（与 docs/ui-demo.html 一致，前端样式以 Demo 定稿为准）：
红＝品牌/需行动/禁止；琥珀＝进行中/注意；灰＝完成/无需动作。
"""
from app import config

# 勾选态指示器内的白色对勾（assets/ 目录素材；文件缺失时优雅退化为纯红底色块）
_CHECK_SVG = (config.ASSET_DIR / "check-white.svg").as_posix()

_APP_QSS = """
* { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; outline: none; }
QWidget#Page { background: #FAF7F4; }

/* ---------- 侧边栏（标准色 40%→20% 叠黑渐变） ---------- */
QWidget#Sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3A030B, stop:1 #1D0106);
}
QLabel#Brand { color: #F7EDEA; font-size: 16px; font-weight: 700; }
QLabel#BrandDot { background: #FDB837; border-radius: 5px; }
QLabel#BrandSub { color: rgba(247,237,234,128); font-size: 11px; }
QPushButton#NavButton {
    color: rgba(247,237,234,185); background: transparent; border: none;
    text-align: left; padding: 10px 12px; border-radius: 9px; font-size: 13px;
}
QPushButton#NavButton:hover { background: rgba(255,255,255,15); }
QPushButton#NavButton:checked {
    background: rgba(253,184,55,33); color: #FDB837; font-weight: 600;
    border-left: 3px solid #FDB837; padding-left: 9px;
}
QLabel#NavBadge {
    background: #92071C; color: #FFFFFF; font-size: 11px; font-weight: 600;
    border-radius: 9px; padding: 1px 7px;
}
QLabel#DemoBadge {
    color: rgba(253,184,55,217); background: rgba(253,184,55,13);
    border: 1px solid rgba(253,184,55,77); border-radius: 8px;
    padding: 7px 10px; font-size: 11px;
}
QLabel#Avatar {
    background: rgba(253,184,55,38); color: #FDB837; border-radius: 14px;
    font-size: 12px; font-weight: 700;
}
QLabel#UserChipName { color: rgba(247,237,234,153); font-size: 12px; }

/* ---------- 页面通用 ---------- */
QLabel#PageTitle { font-size: 20px; font-weight: 700; color: #241A1D; }
QLabel#Muted { color: #8A8378; font-size: 12.5px; }
QLabel#StatValue { font-size: 22px; font-weight: 800; color: #241A1D; }
QFrame#Card { background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 14px; }
QFrame#VLine { background: rgba(170,169,161,107); }
QLabel#Banner {
    background: rgba(146,7,28,20); color: #92071C;
    border: 1px solid rgba(146,7,28,46); border-radius: 10px;
    padding: 12px 16px; font-size: 13.5px;
}
QLabel#Toast {
    background: #2B060F; color: #F7EDEA; font-size: 13px;
    border-left: 3px solid #FDB837; border-radius: 10px; padding: 11px 18px;
}

/* ---------- 控件 ---------- */
QPushButton#Primary {
    background: #92071C; color: #FFFFFF; border: none; border-radius: 9px;
    padding: 9px 20px; font-size: 13.5px; font-weight: 600;
}
QPushButton#Primary:hover { background: #7A0617; }
QPushButton#Primary:disabled { background: rgba(170,169,161,128); }
QPushButton#Ghost {
    background: #FFFFFF; color: #5C534E; border: 1px solid rgba(170,169,161,107);
    border-radius: 9px; padding: 8px 16px; font-size: 13px; font-weight: 600;
}
QPushButton#Ghost:hover { border-color: #92071C; color: #92071C; }
QPushButton#DangerGhost {
    background: rgba(146,7,28,20); color: #92071C; border: none;
    border-radius: 9px; padding: 8px 16px; font-size: 13px; font-weight: 600;
}
QPushButton#DangerGhost:hover { background: rgba(146,7,28,31); }

QPushButton#Sel {
    background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 9px;
    padding: 8px 14px; font-weight: 600; color: #241A1D;
}
QPushButton#Sel:hover { border-color: #92071C; }
QMenu#CourseMenu, QMenu#TrayMenu {
    background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 10px;
    padding: 6px;
}
QMenu#CourseMenu::item, QMenu#TrayMenu::item {
    background: transparent; color: #241A1D; padding: 9px 26px 9px 14px;
    border-radius: 8px; font-size: 13.5px;
}
QMenu#CourseMenu::item:selected, QMenu#TrayMenu::item:selected {
    background: rgba(146,7,28,20); color: #92071C; font-weight: 600;
}
QMenu#CourseMenu::separator, QMenu#TrayMenu::separator {
    height: 1px; background: rgba(170,169,161,51); margin: 4px 8px;
}

QFrame#DirBox { background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 9px; }
QLabel#DirPath { color: #241A1D; font-family: 'Consolas'; font-size: 12px; }

/* ---------- 列表 / 表格 ---------- */
QTreeWidget, QTableWidget {
    background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 14px;
    font-size: 13.5px; color: #241A1D;
}
QHeaderView::section {
    background: #FAF7F4; color: #8A8378; border: none;
    border-bottom: 1px solid rgba(170,169,161,107);
    padding: 8px; font-weight: 600; font-size: 11.5px;
}
/* 左右上角圆化由 widgets.RoundedHeader 在 paintSection 裁剪实现
   （QSS 的 ::section:first/:last 圆角在 Qt 6 下不生效） */
QTreeWidget::item { padding: 5px 2px; }
/* 资料树：数据三列（大小/上传时间/说明）左右各 10px 留白——条目水平内边距 2→12px
   撑宽 ResizeToContents 尺寸提示；该三列条目居中对齐（materials_page），与居中表头同轴 */
QTreeWidget#MatTree::item { padding: 5px 12px; }
QTreeWidget::item:hover { background: rgba(146,7,28,10); }
QTreeWidget::item:selected { background: transparent; color: #241A1D; }
QTableWidget::item { padding: 8px 6px; border-bottom: 1px solid rgba(170,169,161,51); }
QTableWidget::item:hover { background: rgba(146,7,28,10); }
QTableWidget::item:selected { background: rgba(253,184,55,46); color: #241A1D; }

QProgressBar#PBar, QProgressBar#PBarDone {
    background: rgba(170,169,161,41); border: none;
    border-radius: 4px; max-height: 8px; min-height: 8px;
}
QProgressBar#PBar::chunk { background: #FDB837; border-radius: 4px; }
QProgressBar#PBarDone::chunk { background: #9BA79B; border-radius: 4px; }

QListWidget#LoginSteps {
    background: transparent; border: none; font-size: 13.5px; color: #5C534E;
}
QListWidget#LoginSteps::item { padding: 6px 2px; }

/* ---------- 课程管理对话框 ---------- */
QDialog#CourseManager { background: #FAF7F4; }
QDialog#CloseAsk { background: #FAF7F4; }
QListWidget#CourseList {
    background: #FFFFFF; border: 1px solid rgba(170,169,161,107); border-radius: 12px;
    padding: 6px; font-size: 13.5px; color: #241A1D;
}
QListWidget#CourseList::item { padding: 7px 8px; border-radius: 8px; margin: 1px 2px; }
QListWidget#CourseList::item:hover { background: rgba(146,7,28,10); }
QListWidget#CourseList::indicator {
    width: 17px; height: 17px; border: 1.5px solid #B5AEA5; border-radius: 5px;
    background: #FFFFFF; margin-right: 4px;
}
QListWidget#CourseList::indicator:hover { border-color: #92071C; }
QListWidget#CourseList::indicator:checked {
    background: #92071C; border-color: #92071C;
    image: url("%%CHECK%%");
}

/* ---------- 复选框（对话框等处的通用样式） ---------- */
QCheckBox::indicator {
    width: 17px; height: 17px; border: 1.5px solid #B5AEA5; border-radius: 5px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover { border-color: #92071C; }
QCheckBox::indicator:checked {
    background: #92071C; border-color: #92071C;
    image: url("%%CHECK%%");
}

/* ---------- 滚动条（全局细圆角，替换原生粗矩形） ---------- */
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical {
    background: rgba(170,169,161,150); border-radius: 4px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #8A8378; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: rgba(170,169,161,150); border-radius: 4px; min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: #8A8378; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""

APP_QSS = _APP_QSS.replace("%%CHECK%%", _CHECK_SVG)


def status_label(status: str) -> tuple:
    """状态 → (展示文本, 颜色)。三色语义：红=需行动，琥珀=进行中，灰=无需动作。"""
    mapping = {
        "queued":     ("排队中", "#6E6A62"),
        "running":    ("下载中", "#7A5200"),
        "done":       ("完成", "#6E6A62"),
        "updated":    ("已更新", "#7A5200"),
        "skip_record":("跳过（记录）", "#6E6A62"),
        "skip_exist": ("跳过（已存在）", "#6E6A62"),
        "forbidden":  ("禁止下载", "#92071C"),
        "failed":     ("失败", "#92071C"),
        "cancelled":  ("已取消", "#6E6A62"),
        # 作业状态
        "未交":       ("未交", "#92071C"),
        "待批阅":     ("待批阅", "#7A5200"),
        "已提交":     ("已提交", "#6E6A62"),
    }
    return mapping.get(status, (status, "#6E6A62"))


def fmt_bytes(n) -> str:
    """字节数 → 人类可读大小文本。"""
    if not n:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"
