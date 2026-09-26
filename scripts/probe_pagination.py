# -*- coding: utf-8 -*-
"""分页参数探针：实测确认 stu-datalist 的翻页参数名与作用范围。

用法：
  python scripts/probe_pagination.py                       # 探测默认课程（Python程序设计基础）
  python scripts/probe_pagination.py --course 课程名
  python scripts/probe_pagination.py --scan-all            # 全部课程扫描声明总数，找分页样本

流程：会话获取（Cookie 缓存优先，失效自动重登）→ 课程列表 → 逐层找
“声明总数 > 首页行数”的分页层 → 参数矩阵探测第 2 页 → 作用域验证 → 逐页对账。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.core import browser  # noqa: E402
from app.core.api import courses as courses_api  # noqa: E402
from app.core.api import materials as materials_api  # noqa: E402
from app.core.session import ChaoxingSession, RiskControlError, SessionExpiredError  # noqa: E402
from app.utils import setup_logger  # noqa: E402

log = setup_logger("probe")
CANDIDATES = ["pages", "page", "pageNum", "currentPage", "pageIndex"]


def bootstrap():
    """返回 (ses, course_list)。Cookie 缓存优先；失效（SessionExpired）自动重登。"""
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


def fetch_layer(ses, url, referer):
    """拉一层的第 1 页 → {url, html, nodes, enc, declared, ids}。"""
    resp = ses.get(url, headers={"Referer": referer})
    html = materials_api._extract_html(resp.text)
    nodes, enc = materials_api.parse_datalist(html)
    m = materials_api._TOTAL_RE.search(html)
    return {
        "url": url, "html": html, "nodes": nodes, "enc": enc,
        "declared": int(m.group(1)) if m else 0,
        "ids": {n.data_id for n in nodes if n.data_id},
    }


def find_paginated_layer(ses, base, referer, course_name):
    """BFS 找第一个满页层（行数 >= PAGE_SIZE → 可能还有下一页）。

    注意（2026-09-26 实测纠正）：“当前页共 N 个”是每页条数而非该层总数，
    不能用 declared > rows 判断分页；满页（30 条）才意味着可能有下一页。
    返回 (层信息, 层描述) 或 (None, 原因)。
    """
    from collections import deque
    root = fetch_layer(ses, base, referer)
    print(f"  [{course_name}] 根目录：首页 {len(root['nodes'])} 行"
          f"{'（满页，可能有多页）' if len(root['nodes']) >= config.PAGE_SIZE else ''}")
    if len(root["nodes"]) >= config.PAGE_SIZE:
        return root, "根目录"
    queue = deque((nd, nd.relative_path) for nd in root["nodes"]
                  if nd.node_type == materials_api.FOLDER_TYPE and nd.data_id)
    visited = set()
    while queue:
        folder, path = queue.popleft()
        if folder.data_id in visited:
            continue
        visited.add(folder.data_id)
        url = materials_api._folder_url(base, folder, root["enc"])
        layer = fetch_layer(ses, url, referer)
        full = "（满页，可能有多页）" if len(layer["nodes"]) >= config.PAGE_SIZE else ""
        print(f"  [{course_name}] {path}：首页 {len(layer['nodes'])} 行{full}")
        if len(layer["nodes"]) >= config.PAGE_SIZE:
            return layer, f"文件夹 {path}"
        queue.extend((nd, nd.relative_path) for nd in layer["nodes"]
                     if nd.node_type == materials_api.FOLDER_TYPE and nd.data_id)
    return None, "全部层均未满页（无更多页）"


def try_param(ses, first, param, referer):
    """试一个参数名取第 2 页，返回判定结果。"""
    resp = ses.get(first["url"] + f"&{param}=2", headers={"Referer": referer})
    html = materials_api._extract_html(resp.text)
    nodes, _ = materials_api.parse_datalist(html)
    new_ids = {n.data_id for n in nodes if n.data_id} - first["ids"]
    m = materials_api._TOTAL_RE.search(html)
    return {
        "param": param, "status": resp.status_code, "rows": len(nodes),
        "new": len(new_ids), "declared": int(m.group(1)) if m else 0,
        "valid": bool(new_ids),
    }


def paginate_all(ses, first, param, referer, max_pages=None):
    """用确认的参数逐页抓全，直到出现不满页或无新行。返回 (全部节点, 实际页数, 终止原因)。"""
    nodes = list(first["nodes"])
    seen = set(first["ids"])
    max_pages = max_pages or config.MAX_PAGES
    pages = 1
    reason = "第 1 页未满页" if len(nodes) < config.PAGE_SIZE else ""
    for page in range(2, max_pages + 1):
        resp = ses.get(first["url"] + f"&{param}={page}", headers={"Referer": referer})
        html = materials_api._extract_html(resp.text)
        page_nodes, _ = materials_api.parse_datalist(html)
        new = [n for n in page_nodes if n.data_id and n.data_id not in seen]
        pages = page
        if not new:
            reason = "该页无新行（已抓全或参数失效）"
            break
        seen.update(n.data_id for n in new)
        nodes.extend(new)
        if len(page_nodes) < config.PAGE_SIZE:
            reason = "末页不满页（正常终止）"
            break
    else:
        reason = f"达到 MAX_PAGES={max_pages} 上限（可能未抓全！）"
    return nodes, pages, reason


def deep_scan(ses, course_list, skip_ids):
    """逐课程 BFS 找第一个分页层。返回 (course, ctx, layer, desc) 或 None。"""
    for c in course_list:
        if c.clazz_id in skip_ids:
            print(f"  [跳过] {c.name}（{c.clazz_id}）")
            continue
        try:
            ctx = courses_api.open_study_page(ses, c)
            if not ctx.stuenc:
                print(f"  [跳过] {c.name}（{c.clazz_id}）：stuenc 缺失")
                continue
            base = materials_api.root_url(c, ctx.stuenc)
            layer, desc = find_paginated_layer(ses, base, base, f"{c.name}({c.clazz_id})")
        except RiskControlError:
            raise
        except Exception as e:
            print(f"  [跳过] {c.name}（{c.clazz_id}）：{type(e).__name__}: {e}")
            continue
        if layer:
            return c, ctx, layer, desc
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="stu-datalist 分页参数探针")
    ap.add_argument("--course", default="Python程序设计基础", help="课程名（模糊匹配，可命中多门）")
    ap.add_argument("--scan-all", action="store_true", help="跳过指定课程扫描，直接全量深扫")
    ap.add_argument("--skip", default="145747301,138254079,151451749",
                    help="深扫时跳过的 clazzId（逗号分隔；默认跳过两门 Python 课与计算机组成原理）")
    args = ap.parse_args()
    skip_ids = {s.strip() for s in args.skip.split(",") if s.strip()}

    try:
        ses, course_list = bootstrap()
    except Exception as e:
        print(f"[FAIL] 会话获取失败：{e}")
        return 1

    try:
        # ---------- 选目标：先扫指定课程，无分页自动转全量深扫 ----------
        matched = [c for c in course_list if args.course in c.name]
        target = target_layer = target_desc = ctx = None
        if matched and not args.scan_all:
            print(f"[2] 深扫指定课程（{len(matched)} 门）...")
            found = deep_scan(ses, matched, set())
            if found:
                target, ctx, target_layer, target_desc = found
                print(f"[2] 分页层定位：{target_desc}（声明 {target_layer['declared']} / "
                      f"首页 {len(target_layer['nodes'])}）")
        if target is None:
            if matched and not args.scan_all:
                print("[i] 指定课程无分页层，自动转入全量深扫（找到即停）...")
            print("[2] 全量深扫全部课程...")
            found = deep_scan(ses, course_list, skip_ids)
            if not found:
                print("[结论] 全部课程深扫完毕：未发现任何分页层（所有层声明数 == 行数）。")
                print("        资料区可能整页返回（现存数据未触发分页阈值），翻页参数无从验证。")
                return 3
            target, ctx, target_layer, target_desc = found
            print(f"[2] 分页层定位：{target.name}（{target.clazz_id}）{target_desc}"
                  f"（声明 {target_layer['declared']} / 首页 {len(target_layer['nodes'])}）")

        # ---------- 参数矩阵 ----------
        base = materials_api.root_url(target, ctx.stuenc)
        print(f"[3] 翻页控件线索（目标层 HTML 关键字扫描）：")
        for kw in ("showPage", "pager", "pagination", "pageNo", "totalPage",
                   "nextpage", "nextPage", "下一页", "尾页"):
            idx = target_layer["html"].find(kw)
            if idx > -1:
                print(f"  线索“{kw}”@{idx}: ...{target_layer['html'][max(0, idx - 80):idx + 160]}...")
        print(f"[3] 参数矩阵探测（目标层 URL 前 80 字符：{target_layer['url'][:80]}...）")
        results = []
        for param in CANDIDATES:
            r = try_param(ses, target_layer, param, base)
            results.append(r)
            print(f"  {param:<12} HTTP {r['status']}  行数 {r['rows']}  新增 {r['new']}  "
                  f"声明 {r['declared']}  {'← 有效' if r['valid'] else ''}")
        valid = [r for r in results if r["valid"]]
        if not valid:
            print("[FAIL] 参数矩阵全部无效。分析第 1 页翻页控件线索：")
            resp = ses.get(target_layer["url"], headers={"Referer": base})
            html = resp.text
            for kw in ("showPage", "pager", "pagination", "pageNo", "totalPage", "下一页", "尾页"):
                idx = html.find(kw)
                if idx > -1:
                    print(f"  线索“{kw}”@{idx}: ...{html[max(0, idx - 100):idx + 200]}...")
            return 4

        param = valid[0]["param"]
        print(f"[3] 结论：翻页参数 = &{param}=N")

        # ---------- 逐页抓全 ----------
        print("[4] 逐页抓取...")
        all_nodes, pages, reason = paginate_all(ses, target_layer, param, base)
        print(f"  共 {pages} 页，抓到 {len(all_nodes)} 个节点；终止：{reason}")

        # ---------- 作用域验证 ----------
        print("[5] 作用域验证：参数在根目录完整页 / 文件夹 XHR 两种形态下是否一致")
        print(f"  目标层 URL 形态：{'文件夹 XHR（isAjax）' if 'isAjax' in target_layer['url'] else '根目录完整页'}")
        print("  （另一种形态的验证在修复复验时由 verify_mvp 全树对账覆盖）")

        print(f"\n===== 最终结论 =====")
        print(f"翻页参数：&{param}=N（N 从 2 开始）")
        print(f"样本课程：{target.name}（clazzId={target.clazz_id}）")
        print(f"对账：{len(all_nodes)}/{target_layer['declared']}，页数 {pages}")
        return 0
    except RiskControlError as e:
        print(f"[FAIL] 命中风控，立即停止：{e}")
        return 2
    except SessionExpiredError as e:
        print(f"[FAIL] 登录态失效：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
