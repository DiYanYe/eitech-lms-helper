# -*- coding: utf-8 -*-
"""构建期工具：图标/logo.png → 图标/logo.ico（多尺寸，exe/安装器图标用）。

用法（eitech-lms 环境内）：
    python scripts/make_ico.py
依赖 Pillow（requirements-dev.txt），仅在构建机运行，不属于运行时依赖。
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "图标" / "logo.png"
DST = ROOT / "图标" / "logo.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> int:
    if not SRC.exists():
        print(f"[make_ico] 未找到源图：{SRC}")
        return 1
    img = Image.open(SRC)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    # ico 单文件内嵌多尺寸，资源管理器按视图尺寸就近取用
    img.save(DST, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"[make_ico] 已生成 {DST}（{DST.stat().st_size / 1024:.0f} KB，尺寸 {SIZES}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
