# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（onedir + windowed）：
#   构建：在 eitech-lms 环境内、仓库根执行  pyinstaller 东方理工LMS助手.spec --noconfirm
#   产物：dist/东方理工LMS助手/（整个文件夹压 zip 分发）
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('使用说明.txt', '.')]
binaries = []
hiddenimports = []
# DrissionPage 自带配置模板等数据文件，整包收集
for pkg in ('DrissionPage',):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['app/ui/main.py'],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='东方理工LMS助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 不加壳，降低杀软误报
    console=False,      # GUI 程序，无控制台窗口
    icon='assets/logo.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='东方理工LMS助手',
)

# 后置步骤：使用说明放到 exe 旁（datas 里的副本会落进 _internal，同学看不到）
import os
import shutil
shutil.copy2(
    os.path.join(SPECPATH, '使用说明.txt'),
    os.path.join(DISTPATH, '东方理工LMS助手', '使用说明.txt'),
)
