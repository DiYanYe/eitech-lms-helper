# -*- coding: utf-8 -*-
"""资料行时间字段探针：实测确认（1）列表行是否携带上传时间、在哪个元素/属性、
什么格式；（2）cldisk 签名直链响应头是否带 Last-Modified。

用法：
  python scripts/probe_file_time.py                       # 默认课程：计算机组成原理
  python scripts/probe_file_time.py --course 课程名
  python scripts/probe_file_time.py --rows 5              # 多打印几行原始 HTML

只读探测：仅 GET/HEAD，不下载文件、不写任何文件（登录成功会缓存 Cookie，与 GUI 行为一致）。
输出只到控制台；原始 HTML 可能含个人信息，不写入仓库文档，只把字段结论沉淀进
docs/接口实测文档.md。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from app import config  # noqa: E402
from app.core import browser, downloader  # noqa: E402
from app.core.api import courses as courses_api  # noqa: E402
from app.core.api import materials as materials_api  # noqa: E402
from app.core.session import ChaoxingSession, RiskControlError, SessionExpiredError  # noqa: E402

# toOpen 全参数（13 个）：现有 _TOOPEN_RE 只截到第 10 个（enc），这里补全后 3 个
_TOOPEN_FULL_RE = re.compile(
    r"toOpen\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*'([^']*)'\s*,\s*(\d+)\s*,"
    r"\s*'((?:[^'\\]|\\.)*)'\s*,\s*'((?:[^'\\]|\\.)*)'\s*,\s*'((?:[^'\\]|\\.)*)'\s*,"
    r"\s*(\d+)\s*,\s*(\d+)\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,"
    r"\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
)

_TIME_HINTS = ("上传", "时间", "日期", "time", "date", "create", "update")


def bootstrap():
    """Cookie 缓存优先；失效/缺失自动弹 Edge 手动登录并缓存（与 probe_pagination 一致）。"""
    cookies = browser.load_cookies()
    if cookies:
        ses = ChaoxingSession(cookies)
        try:
            return ses, courses_api.fetch_course_list(ses)
        except SessionExpiredError:
            ses.close()
            print("[1] 缓存 Cookie 已失效，请在弹出的 Edge 中重新登录...")
    cookies, _ua = browser.login_interactive()
    browser.save_cookies(cookies)
    ses = ChaoxingSession(cookies)
    print("[1] 重新登录成功，Cookie 已刷新缓存")
    return ses, courses_api.fetch_course_list(ses)


def dump_rows(html: str, limit: int):
    """打印前 N 行原始 HTML + 行内 li 元素清单 + 时间线索扫描。"""
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("ul.dataBody_td")
    print(f"\n[2] 根层共 {len(rows)} 行；下面打印前 {min(limit, len(rows))} 行原始 HTML")
    for i, ul in enumerate(rows[:limit]):
        print(f"\n---- 行 {i + 1} 原始 HTML（截断 4000 字符）----")
        print(str(ul)[:4000])
        print(f"---- 行 {i + 1} 元素清单 ----")
        print(f"  ul.attrs = {ul.attrs}")
        for li in ul.find_all("li"):
            print(f"  li class={li.get('class')} attrs={ {k: v for k, v in li.attrs.items() if k != 'class'} }"
                  f" text={li.get_text(' ', strip=True)[:80]!r}")

    print("\n[3] 时间线索扫描（全行 HTML 关键字定位）")
    raw = str(rows[0]) if rows else html
    for kw in _TIME_HINTS:
        idx = raw.find(kw)
        if idx > -1:
            print(f"  线索“{kw}”@{idx}: ...{raw[max(0, idx - 120):idx + 160]}...")


def dump_toopen(html: str):
    """打印 toOpen 的全部 13 个参数，确认第 11/12/13 位是否含时间戳。"""
    soup = BeautifulSoup(html, "lxml")
    print("\n[4] toOpen 全参数（前 3 行）")
    for i, ul in enumerate(soup.select("ul.dataBody_td")[:3]):
        m = _TOOPEN_FULL_RE.search(str(ul))
        if not m:
            print(f"  行 {i + 1}: toOpen 未匹配（可能无 onclick）")
            continue
        names = ["name", "type", "dataId", "loadurl", "objectId", "url",
                 "flag", "source", "clazzid", "enc", "arg11", "arg12", "arg13"]
        print(f"  行 {i + 1}: " + " | ".join(
            f"{n}={m.group(j + 1)[:60]!r}" for j, n in enumerate(names)))


def probe_cldisk(ses, course, node, base):
    """对一个可下载文件：resolve 直链 → HEAD（带 Referer）→ 打印响应头关注项。"""
    print(f"\n[5] cldisk 直链响应头探测：{node.relative_path}")
    direct, meta = downloader.resolve_direct_url(ses, course, node, base)
    if not direct:
        print(f"  resolve 失败：{meta}")
        return
    print(f"  直链域名：{direct.split('/')[2]}（路径与签名参数不打印）")
    try:
        resp = ses.request("HEAD", direct, headers={"Referer": f"{config.MOOC1}/"})
    except RiskControlError as e:
        print(f"  HEAD 命中风控：{e}")
        return
    print(f"  HEAD HTTP {resp.status_code}")
    for key in ("last-modified", "etag", "content-length", "content-type",
                "content-disposition", "date", "accept-ranges"):
        val = resp.headers.get(key)
        print(f"    {key}: {val if val is not None else '（无）'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="资料行时间字段 + cldisk 响应头探针")
    ap.add_argument("--course", default="计算机组成原理", help="课程名（模糊匹配）")
    ap.add_argument("--rows", type=int, default=3, help="打印原始 HTML 的行数")
    args = ap.parse_args()

    try:
        ses, course_list = bootstrap()
    except Exception as e:
        print(f"[FAIL] 会话获取失败：{e}")
        return 1

    try:
        matched = [c for c in course_list if args.course in c.name]
        if not matched:
            print(f"[FAIL] 未匹配到课程“{args.course}”，可选课程：")
            for c in course_list:
                print(f"  - {c.name}（clazzId={c.clazz_id}）")
            return 2
        course = matched[0]
        print(f"[1] 课程定位：{course.name}（courseId={course.course_id}, clazzId={course.clazz_id}）")

        ctx = courses_api.open_study_page(ses, course)
        if not ctx.stuenc:
            print("[FAIL] stuenc 缺失，无法进入资料区")
            return 2
        base = materials_api.root_url(course, ctx.stuenc)
        resp = ses.get(base, headers={"Referer": base})
        html = materials_api._extract_html(resp.text)
        if "dataBody" not in html:
            print(f"[FAIL] 根层未返回 dataBody（HTTP {resp.status_code}，长度 {len(html)}）")
            return 2

        dump_rows(html, args.rows)
        dump_toopen(html)

        nodes, enc = materials_api.parse_datalist(html)
        target = next((n for n in nodes if not n.children
                       and n.node_type != materials_api.FOLDER_TYPE
                       and n.is_down and n.data_id and not n.special), None)
        if target is None:
            folder = next((n for n in nodes
                           if n.node_type == materials_api.FOLDER_TYPE and n.data_id and enc), None)
            if folder:
                print(f"\n[4.5] 根层无文件，下钻文件夹「{folder.name}」（dataId={folder.data_id}）")
                furl = materials_api._folder_url(base, folder, enc)
                r2 = ses.get(furl, headers={"Referer": base})
                html2 = materials_api._extract_html(r2.text)
                dump_rows(html2, args.rows)
                nodes = materials_api.parse_datalist(html2)[0]
                target = next((n for n in nodes if not n.children
                               and n.node_type != materials_api.FOLDER_TYPE
                               and n.is_down and n.data_id and not n.special), None)

        print("\n[4.6] 时间提取自检（当前解析函数对实测 HTML 的输出）")
        for nd in nodes[:5]:
            print(f"  {nd.relative_path[:50]!r}: remote_time_text={nd.remote_time_text!r} "
                  f"remote_mtime={nd.remote_mtime}")

        if target is None:
            print("\n[5] 未找到可下载文件，跳过 cldisk 探测")
        else:
            probe_cldisk(ses, course, target, base)
        return 0
    except RiskControlError as e:
        print(f"[FAIL] 命中风控，立即停止：{e}")
        return 2
    except SessionExpiredError as e:
        print(f"[FAIL] 登录态失效：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())