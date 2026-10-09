# -*- coding: utf-8 -*-
"""DrissionPage 浏览器桥：启动系统 Edge/Chrome（持久化 profile）、手动 CAS 登录、Cookie 导出。

安全约定：Cookie 值不打印、不写日志。
本地缓存：Cookie 以 Windows DPAPI（CurrentUser 作用域）加密存于 data/cookies.bin；
拷贝到其他机器/用户无法解密，解密失败自动回退重新登录。旧明文 cookies.json
首次加载时自动加密迁移并删除。
"""
import json
import time
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage

from app import config
from app.core.secret_box import SecretBoxError, dpapi_decrypt, dpapi_encrypt


class LoginTimeoutError(Exception):
    """等待手动登录超时。"""


class BrowserNotFoundError(Exception):
    """未找到可用的 Chromium 系浏览器（Edge/Chrome）。"""


def cookies_cache_path() -> Path:
    """加密 Cookie 缓存路径（DPAPI blob，非明文）。"""
    return config.DATA_DIR / "cookies.bin"


def _legacy_json_path() -> Path:
    """历史明文缓存路径（仅用于一次性迁移，2026-09-26 前的版本写入）。"""
    return config.DATA_DIR / "cookies.json"


def _parse(data) -> dict | None:
    if isinstance(data, dict) and data.get("vc3") and data.get("_uid"):
        return data
    return None


def load_cookies():
    """读取本地 Cookie 缓存；不存在 / 损坏 / 缺关键项返回 None（调用方回退重新登录）。

    迁移：加密缓存损坏时若旧明文 cookies.json 仍在，则读明文并重新加密迁移。
    """
    p = cookies_cache_path()
    if p.exists():
        try:
            data = json.loads(dpapi_decrypt(p.read_bytes()).decode("utf-8"))
        except (OSError, ValueError, SecretBoxError):
            data = None
        cookies = _parse(data)
        if cookies:
            return cookies
    legacy = _legacy_json_path()
    if legacy.exists():
        try:
            cookies = _parse(json.loads(legacy.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
        if cookies:
            save_cookies(cookies)  # 迁移：加密落盘并删除明文
        return cookies
    return None


def save_cookies(cookies: dict):
    """Cookie 以 DPAPI 加密落盘；成功后清理历史明文文件（迁移收尾）。"""
    p = cookies_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(cookies, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    p.write_bytes(dpapi_encrypt(raw))
    try:
        _legacy_json_path().unlink(missing_ok=True)
    except OSError:
        pass  # 明文清理失败不影响加密文件已写成功的主流程


def discard_cookies():
    """清除全部本地 Cookie 缓存（加密文件与历史明文）。"""
    cookies_cache_path().unlink(missing_ok=True)
    try:
        _legacy_json_path().unlink(missing_ok=True)
    except OSError:
        pass


# 浏览器探测表：Edge 优先（Windows 自带、与历史版本行为一致），Chrome 回退。
# 每项 = (显示名, 专用 profile 目录, 常规安装路径候选, 注册表 App Paths 子键名)
_BROWSER_CANDIDATES = [
    ("Microsoft Edge", config.EDGE_PROFILE,
     [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
     "msedge.exe"),
    ("Google Chrome", config.CHROME_PROFILE,
     [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
      str(Path.home() / "AppData" / "Local" / "Google" / "Chrome"
          / "Application" / "chrome.exe")],   # 现代 Chrome 默认按用户安装
     "chrome.exe"),
]
_PROFILE_BY_NAME = {name: profile for name, profile, _paths, _exe in _BROWSER_CANDIDATES}


def _registry_lookup(exe_name: str) -> str | None:
    """查注册表 App Paths（先 HKLM 后 HKCU，覆盖 Chrome 按用户安装），未命中返回 None。"""
    try:
        import winreg
    except ImportError:   # 非 Windows（理论上不会走到，登录链路仅限 Windows）
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(
                hive,
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and Path(val).exists():
                    return val
        except OSError:
            continue
    return None


def find_browser() -> tuple:
    """定位系统 Chromium 系浏览器（Edge 优先，Chrome 回退）→ (exe 路径, 显示名)。"""
    for name, _profile, paths, exe in _BROWSER_CANDIDATES:
        for p in paths:
            if Path(p).exists():
                return p, name
        reg = _registry_lookup(exe)
        if reg:
            return reg, name
    raise BrowserNotFoundError("未找到 Microsoft Edge 或 Google Chrome，请安装其一后重试")


def build_options() -> tuple:
    """构建 ChromiumOptions → (options, 浏览器显示名)。

    专用持久化 profile 目录（按浏览器隔离），不与用户日常浏览器冲突；登录态长期保留。
    """
    browser_path, browser_name = find_browser()
    profile = _PROFILE_BY_NAME[browser_name]
    profile.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_browser_path(browser_path)
    co.set_user_data_path(str(profile))
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    return co, browser_name


def export_cookies(page) -> dict:
    """导出 .chaoxing.com / .eitech.edu.cn 域 Cookie 为 {name: value}。

    MVP 简化：不同子域同名 Cookie 以最后一次出现为准。
    """
    cookies: dict = {}
    for c in page.cookies(all_domains=True):
        domain = str(c.get("domain", ""))
        name = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue
        if ("chaoxing.com" in domain) or ("eitech.edu.cn" in domain):
            cookies[name] = value
    return cookies


def login_interactive(timeout: int = None, should_stop=None):
    """打开登录页，等待用户完成学校 CAS 登录；成功返回 (cookies, user_agent)。

    判定标准（实测）：任意域 Cookie 中出现 vc3 且页面已离开 authserver 域。
    profile 已持久化——此前登录过且未失效时，本函数会直接快速通过。
    should_stop：可选无参回调，轮询间隙命中即取消并返回 None（finally 仍关浏览器）。
    """
    timeout = timeout or config.LOGIN_TIMEOUT
    co, browser_name = build_options()
    page = ChromiumPage(co)
    try:
        ua = page.user_agent
        print(f"  已启动 {browser_name}，请在弹出的窗口中完成统一身份认证登录（最长等待 {timeout} 秒）...")
        page.get(config.LOGIN_PAGE)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if should_stop and should_stop():
                return None
            url = page.url or ""
            names = {c.get("name") for c in page.cookies(all_domains=True)}
            if "vc3" in names and "authserver" not in url:
                return export_cookies(page), ua
            time.sleep(2)
        raise LoginTimeoutError(f"等待登录超过 {timeout} 秒")
    finally:
        try:
            page.quit()  # 关闭浏览器；登录态已保存在持久化 profile 中
        except Exception:
            pass
