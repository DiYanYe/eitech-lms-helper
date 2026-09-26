# -*- coding: utf-8 -*-
"""文件类型图标：加载 图标/ 目录下的彩色 SVG（与 docs/ui-demo.html 同源素材）。

未提供素材的类型（压缩包/未知）回退为灰底扩展名徽章（QPainter 绘制）。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app import config

ICON_DIR = config.ASSET_DIR
_SVG_MAP = {
    "pdf": "文件类型-pdf.svg",
    "doc": "文件类型-文档.svg", "docx": "文件类型-文档.svg",
    "ppt": "文件类型-ppt.svg", "pptx": "文件类型-ppt.svg",
    "mp4": "文件类型-视频.svg", "mov": "文件类型-视频.svg", "avi": "文件类型-视频.svg",
    "mkv": "文件类型-视频.svg", "flv": "文件类型-视频.svg",
    "mp3": "文件类型-音频.svg", "wav": "文件类型-音频.svg", "m4a": "文件类型-音频.svg",
    "flac": "文件类型-音频.svg", "aac": "文件类型-音频.svg",
}
_cache: dict = {}


def file_icon(ext: str) -> QIcon:
    """扩展名 → 彩色 SVG 图标（22pt @2x 渲染，保证高分屏清晰）。"""
    ext = (ext or "").lower()
    if ext in _cache:
        return _cache[ext]
    icon = None
    name = _SVG_MAP.get(ext)
    if name and (ICON_DIR / name).exists():
        renderer = QSvgRenderer(str(ICON_DIR / name))
        if renderer.isValid():
            pm = QPixmap(44, 44)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            pm.setDevicePixelRatio(2.0)
            icon = QIcon(pm)
    if icon is None:
        icon = _badge_icon((ext[:4] or "file").upper())
    _cache[ext] = icon
    return icon


def app_icon() -> QIcon:
    """应用图标（托盘/窗口）：优先加载 图标/logo.*（正式 logo 落地零代码接入），
    否则绘制品牌占位图（VI 红 #92071C 圆角底 + 白「东」）。"""
    if "app" in _cache:
        return _cache["app"]
    for name in ("logo.png", "logo.ico", "logo.svg"):
        path = ICON_DIR / name
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                _cache["app"] = icon
                return icon
            break
    pm = QPixmap(128, 128)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#92071C"))
    painter.drawRoundedRect(2, 2, 124, 124, 28, 28)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(72)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "东")
    painter.end()
    icon = QIcon(pm)
    _cache["app"] = icon
    return icon


def _badge_icon(text: str) -> QIcon:
    pm = QPixmap(44, 44)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F1EFEA"))
    painter.drawRoundedRect(1, 1, 42, 42, 10, 10)
    painter.setPen(QColor("#6E6A62"))
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(12)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)
