# -*- coding: utf-8 -*-
"""MVP 验证脚本：端到端跑通 登录 → 课程 → enc → 资料树 → 下载 → 跳过 → 作业。

用法（使用 eitech-lms 环境）：
  C:/Users/DIYAN/scoop/persist/miniconda3/envs/eitech-lms/python.exe scripts/verify_mvp.py
  可选参数：
    --course 计算机组成原理   目标课程名（模糊匹配）
    --no-download             只验证链路，不下载
    --max-files N             最多下载 N 个文件（0=全部）
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.core import browser, downloader  # noqa: E402
from app.core.api import courses as courses_api  # noqa: E402
from app.core.api import homework as homework_api  # noqa: E402
from app.core.api import materials as materials_api  # noqa: E402
from app.core.session import ChaoxingSession, RiskControlError, SessionExpiredError  # noqa: E402
from app.core.storage import Storage  # noqa: E402
from app.utils import sanitize_filename, setup_logger  # noqa: E402

log = setup_logger()
RESULTS = []   # (步骤, 是否通过, 摘要)
TODOS = []     # 运行中发现的待办/未决点


def step(n, title):
    print(f"\n===== Step{n} {title} =====")


def record(n, ok, summary):
    RESULTS.append((n, ok, summary))
    print(f"  → Step{n} {'PASS' if ok else 'FAIL'}：{summary}")


def print_tree(nodes):
    for nd in sorted(nodes, key=lambda x: x.relative_path):
        depth = nd.relative_path.count("/")
        indent = "    " * depth
        perm = "" if nd.node_type == "afolder" else ("  [禁下载]" if not nd.is_down else "")
        size = nd.size_text or "-"
        print(f"{indent}|- [{nd.node_type}] {nd.name}  {size}{perm}")


def write_report(args, dl_report=None, tree=None, homework=None, course=None):
    """按“运行时间戳分节”追加写入验证报告（保留各次运行结论）。"""
    sections = []
    sections.append(f"# MVP 验证报告 · {datetime.now():%Y-%m-%d %H:%M:%S}")
    sections.append(f"- 参数：course={args.course}，no_download={args.no_download}，max_files={args.max_files}")
    sections.append(f"- 课程：{course.name if course else '未定位'}")
    sections.append("\n## 步骤结果\n")
    sections.append("| 步骤 | 结果 | 摘要 |")
    sections.append("| --- | --- | --- |")
    for n, ok, summary in RESULTS:
        sections.append(f"| Step{n} | {'PASS' if ok else 'FAIL'} | {summary} |")
    if tree is not None:
        folders = [n for n in tree.nodes if n.node_type == "afolder"]
        files = [n for n in tree.nodes if n.node_type not in ("afolder", "tch-courseware")]
        sections.append(f"\n## 资料树摘要\n\n- 文件夹 {len(folders)} 个，文件 {len(files)} 个，"
                        f"页面声明总数 {tree.total_declared}")
        for nd in tree.nodes:
            if nd.node_type == "afolder":
                sections.append(f"- 目录：{nd.relative_path}（子节点 {len(nd.children)}）")
    if dl_report is not None:
        if dl_report.header_experiment:
            sections.append("\n## cldisk 直链请求头实验\n")
            sections.append("| 文件 | 尝试 | 结果 |")
            sections.append("| --- | --- | --- |")
            for rel, label, note, verdict in dl_report.header_experiment:
                sections.append(f"| {rel} | {label} | {note}（{verdict}） |")
            sections.append(f"\n**最优策略：{dl_report.best_strategy or '全部失败'}**")
        if dl_report.results:
            sections.append("\n## 下载明细\n")
            for r in dl_report.results:
                size = f"{r.bytes_written} bytes" if r.bytes_written else ""
                sections.append(f"- `{r.status}` {r.relative_path} {size} {r.detail}")
    if homework is not None:
        sections.append("\n## 作业列表\n")
        if homework:
            for h in homework:
                sections.append(f"- [{h.status or '无状态'}] {h.title}（{h.time_text or '无时间'}）")
        else:
            sections.append("- （无作业或未获取）")
    if TODOS:
        sections.append("\n## TODO / 未决点\n")
        for t in TODOS:
            sections.append(f"- {t}")
    config.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.REPORT_PATH, "a", encoding="utf-8") as f:
        f.write("\n\n".join(sections) + "\n\n---\n")
    print(f"\n报告已写入：{config.REPORT_PATH}")


def main() -> int:
    ap = argparse.ArgumentParser(description="超星 LMS MVP 验证")
    ap.add_argument("--course", default=config.TARGET_COURSE_NAME, help="目标课程名（模糊匹配）")
    ap.add_argument("--no-download", action="store_true", help="只验证链路，不下载")
    ap.add_argument("--max-files", type=int, default=0, help="最多下载 N 个文件，0=全部")
    args = ap.parse_args()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    # ---------- Step1 会话获取（Cookie 缓存优先，失效自动重登） ----------
    step(1, "会话获取（Cookie 缓存 → 失效则 DrissionPage 登录）")
    try:
        cookies = browser.load_cookies()
        if cookies:
            record(1, True, f"复用本地 Cookie 缓存：{len(cookies)} 项（免登录）")
        else:
            cookies, _ua = browser.login_interactive()
            browser.save_cookies(cookies)
            record(1, "vc3" in cookies,
                   f"手动登录成功：导出 {len(cookies)} 项并缓存（vc3={'有' if 'vc3' in cookies else '无'}）")
    except Exception as e:
        record(1, False, f"会话获取失败：{e}")
        write_report(args)
        return 1
    if not ("vc3" in cookies):
        write_report(args)
        return 1

    ses = ChaoxingSession(cookies)
    storage = Storage()

    # ---------- Step2 课程列表（缓存失效时自动重登一次） ----------
    step(2, "课程列表（POST courselistdata）")
    course_list = None
    try:
        course_list = courses_api.fetch_course_list(ses)
    except SessionExpiredError:
        browser.discard_cookies()
        record(1, True, "缓存 Cookie 已失效，已重新登录")
        ses.close()
        cookies, _ua = browser.login_interactive()
        browser.save_cookies(cookies)
        ses = ChaoxingSession(cookies)
        course_list = courses_api.fetch_course_list(ses)
    target = next((c for c in course_list if args.course in c.name), None)
    detail = f"共 {len(course_list)} 门课；"
    if target:
        detail += (f"目标“{target.name}”已定位（courseId={target.course_id}, "
                   f"clazzId={target.clazz_id}, cpi={target.cpi or '?'}）")
    else:
        detail += f"未找到名称含“{args.course}”的课程"
        for c in course_list[:20]:
            print(f"   - {c.name}")
    record(2, target is not None, detail)
    if target is None:
        write_report(args)
        return 1
    course = target
    tree = None
    homework = None
    dl_report = downloader.DownloadReport()
    exit_code = 0
    try:
        # ---------- Step3 学习页 enc ----------
        step(3, "学习页三 enc 提取（stuenc / work-enc；coursedata-enc 在 Step4）")
        ctx = courses_api.open_study_page(ses, target)
        ok3 = bool(ctx.stuenc) and bool(ctx.work_list_url)
        wl = ctx.work_list_url.split("?")[0] + ("?…" if ctx.work_list_url else "")
        record(3, ok3, f"stuenc={ctx.stuenc[:8]}…（{'有效' if ctx.stuenc else '缺失'}）；"
                       f"work_list={wl or '缺失'}")
        if not ctx.stuenc:
            TODOS.append("学习页未提取到 stuenc，需核查 stucoursemiddle 跳转链")

        # ---------- Step4 资料树 ----------
        step(4, "资料树递归（stu-datalist + isAjax 文件夹遍历）")
        tree = materials_api.fetch_tree(ses, target, ctx.stuenc)
        folders = [n for n in tree.nodes if n.node_type == "afolder"]
        files = [n for n in tree.nodes if n.node_type not in ("afolder", "tch-courseware")]
        print_tree(tree.nodes)
        record(4, bool(tree.nodes), f"文件夹 {len(folders)} 个 / 文件 {len(files)} 个 / "
                                    f"coursedata-enc={'有' if tree.coursedata_enc else '无'} / "
                                    f"页面声明总数 {tree.total_declared}")
        TODOS.extend(tree.todos)

        # ---------- Step5 完整下载 ----------
        if args.no_download:
            record(5, True, "已跳过（--no-download）")
            record(6, True, "已跳过（--no-download）")
        else:
            todo_files = files if args.max_files == 0 else files[:args.max_files]
            step(5, f"单课程完整下载（{len(todo_files)} 个文件，顺序 + 随机延迟）")
            referer = materials_api.root_url(target, ctx.stuenc)
            results = downloader.download_course(ses, target, todo_files, storage, referer, dl_report)
            for r in results:
                size = f"（{r.bytes_written} bytes）" if r.bytes_written else ""
                print(f"   {r.status:<12} {r.relative_path} {size} {r.detail}")
            n_done = sum(1 for r in results if r.status == "done")
            n_upd = sum(1 for r in results if r.status == "updated")
            n_skip = sum(1 for r in results if r.status.startswith("skip"))
            n_forb = sum(1 for r in results if r.status == "forbidden")
            n_fail = sum(1 for r in results if r.status == "failed")
            # 首次运行应为全 done；复跑场景全 skip 也是预期（跳过逻辑生效）；
            # updated = 时间戳校验判定平台较新，已覆盖本地旧文件
            all_accounted = (n_done + n_upd + n_skip + n_forb) == len(todo_files)
            record(5, n_fail == 0 and all_accounted and len(todo_files) > 0,
                   f"成功 {n_done}（含更新 {n_upd}）/ 跳过 {n_skip} / 禁止 {n_forb} / 失败 {n_fail}")
            TODOS.extend([f"下载失败：{r.relative_path}（{r.detail}）"
                          for r in results if r.status == "failed"])

            # ---------- Step6 二次下载验证跳过 ----------
            step(6, "二次下载验证跳过逻辑")
            results2 = downloader.download_course(ses, target, todo_files, storage, referer, dl_report)
            all_skip = bool(results2) and all(
                r.status.startswith("skip") or r.status == "forbidden" for r in results2)
            record(6, all_skip, f"复跑 {len(results2)} 个文件，全部跳过={'是' if all_skip else '否'}")

        # ---------- Step7 作业列表 ----------
        step(7, "作业列表（work/list）")
        homework = homework_api.fetch_homework(ses, ctx.work_list_url)
        for h in homework:
            print(f"   [{h.status or '?'}] {h.title}  {h.time_text}")
        record(7, bool(homework), f"共获取 {len(homework)} 条作业")

    except (RiskControlError, SessionExpiredError) as e:
        record(0, False, f"链路中止：{e}")
        TODOS.append(str(e))
        exit_code = 2
    except Exception as e:  # 未知异常：记录后退出，报告照常生成
        record(0, False, f"未预期异常：{type(e).__name__}: {e}")
        TODOS.append(f"未预期异常：{type(e).__name__}: {e}")
        exit_code = 3
    finally:
        ses.close()
        storage.close()
        write_report(args, dl_report=dl_report, tree=tree, homework=homework, course=course)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
