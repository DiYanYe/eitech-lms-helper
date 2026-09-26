# -*- coding: utf-8 -*-
"""GUI 入口：python -m app.ui.main"""
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import APP_QSS


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")                     # 跨版本一致的基础控件外观
    app.setApplicationName("东方理工 LMS 助手")
    app.setOrganizationName("eitech")
    app.setStyleSheet(APP_QSS)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    win = MainWindow()
    win.resize(1120, 740)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
