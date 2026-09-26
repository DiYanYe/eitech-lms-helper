# -*- coding: utf-8 -*-
"""通用小工具：文件名清洗、大小文本解析、日志。"""
import logging
import re

from app import config

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def sanitize_filename(name: str, max_len: int = 150) -> str:
    """清洗文件/文件夹名中的 Windows 非法字符。"""
    name = _ZERO_WIDTH.sub("", name or "").strip()
    name = _ILLEGAL.sub("_", name).strip(" .")
    return name[:max_len] or "未命名"


def parse_size_text(text: str):
    """把 '14KB' / '3MB' 等展示文本解析为近似字节数；无法解析返回 None。"""
    if not text:
        return None
    m = re.search(r"([\d.]+)\s*(GB|MB|KB|B)", text, re.I)
    if not m:
        return None
    val = float(m.group(1))
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[m.group(2).upper()]
    return int(val * mult)


def clean_text(s: str) -> str:
    """去零宽字符并压缩空白。"""
    s = _ZERO_WIDTH.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip()


def setup_logger(name: str = "mvp") -> logging.Logger:
    """控制台 + 文件双通道日志。注意：任何地方不得记录 Cookie 值。"""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    filehd = logging.FileHandler(config.LOG_DIR / "mvp.log", encoding="utf-8")
    filehd.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console)
    logger.addHandler(filehd)
    return logger
