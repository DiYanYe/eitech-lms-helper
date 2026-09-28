# -*- coding: utf-8 -*-
"""下载器：downloadData → cldisk 签名直链，按网页目录结构落盘。

核心流程（2026-09-25 实测依据）：
1. GET mooc1/coursedata/downloadData?dataId=&classId=&cpi=&courseId=&ut=s
   （不跟随重定向）→ 302 Location = d0.cldisk.com/download/{objectId}?at_=&ak_=&ad_=&fn=
2. 对签名直链做请求头实验（A 裸请求 / B 带 Referer / C 带 Set-Cookie / D loadurl 回退），
   首个成功策略记忆后供后续文件复用——实验矩阵写入验证报告
3. 流式写 .part → 完成改名；同名冲突加序号；已下载（记录或本地文件）跳过

时间戳校验（2026-09-28）：每文件按「平台上传时间 vs 本地基线（记录 remote_mtime / 本地文件
mtime）」比对，平台较新 → 重新下载并**直接覆盖**本地旧文件（状态 updated），本地 mtime 回写为
平台时间；本地较新（用户改过）不覆盖。平台时间缺省取列表 DOM，解析不到时回退 cldisk 响应头
Last-Modified。

风控约定：顺序下载 + 文件间随机延迟；尊重 isdown=0（教师禁止下载）不强行获取。
"""
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app import config
from app.utils import parse_size_text, sanitize_filename

REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class DownloadResult:
    relative_path: str
    status: str            # done / updated / skip_record / skip_exist / forbidden / failed / cancelled
    detail: str = ""
    bytes_written: int = 0


@dataclass
class DownloadReport:
    results: list = field(default_factory=list)
    # 每条：(文件, 尝试标签, HTTP状态, content-type, 结论)
    header_experiment: list = field(default_factory=list)
    best_strategy: str = ""


def cleanup_part_files(root: Path = None) -> int:
    """清理历史运行残留的 .part 临时文件，返回清理数量。"""
    base = root or config.DOWNLOAD_ROOT
    n = 0
    if base.exists():
        for p in base.rglob("*.part"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


def _final_path(root: Path, course_name: str, relative_path: str) -> Path:
    """落盘路径：下载根目录/课程名/relative_path（课程文件夹下直接放资料文件）。"""
    parts = [sanitize_filename(p) for p in relative_path.split("/") if p]
    return root / sanitize_filename(course_name) / Path(*parts)


def _dedupe(path: Path) -> Path:
    """同名冲突自动加 (1)(2)... 序号。"""
    if not path.exists():
        return path
    for i in range(1, 100):
        cand = path.with_name(f"{path.stem}({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _local_file_matches(dest: Path, size_text: str) -> bool:
    """本地文件已存在且大小匹配（展示大小为约数，允许 5%/2KB 容差）。"""
    if not dest.exists():
        return False
    expected = parse_size_text(size_text)
    if expected is None:
        return True  # 无大小参考：存在即认为已下载（MVP 策略）
    actual = dest.stat().st_size
    return abs(actual - expected) <= max(2048, expected * 0.05)


def _size_mismatch(bytes_total, size_hint) -> bool:
    """记录/本地精确字节数与平台展示约数的大小比对（容差同 _local_file_matches）。

    任一侧未知时返回 False（宁可不判变化，也不误覆盖）。
    """
    if bytes_total is None or size_hint is None:
        return False
    return abs(bytes_total - size_hint) > max(2048, size_hint * 0.05)


def _fmt_time(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "未知"


def _plan_action(node, dest: Path, rec, remote_epoch):
    """时间戳校验决策（纯函数，便于离线测试）→ (action, detail)。

    action：
      skip_record 已下载且平台无更新（记录命中）
      skip_exist  本地文件已是平台文件（无记录场景，或本地时间一致）
      fresh       需要下载（本地无对应文件）
      update      平台文件较新 / 旧记录与平台大小不符 → 重新下载并直接覆盖
    remote_epoch：平台上传时间（Unix 秒；None = 平台时间不可用，退化旧行为）。
    """
    exists = dest.exists()
    local_mtime = int(dest.stat().st_mtime) if exists else None
    size_hint = parse_size_text(node.size_text)
    rec_mtime = rec["remote_mtime"] if rec is not None else None
    rec_bytes = rec["bytes_total"] if rec is not None else None

    if rec is not None:
        if remote_epoch is not None and rec_mtime is not None:
            if remote_epoch > rec_mtime:
                return "update", (f"平台已更新：{_fmt_time(remote_epoch)}"
                                  f"（本地旧版 {_fmt_time(rec_mtime)}）")
            if remote_epoch == rec_mtime and _size_mismatch(rec_bytes, size_hint):
                return "update", "平台大小与记录不符（时间精度内重传）"
            return "skip_record", "下载记录命中"
        if remote_epoch is not None and rec_mtime is None:
            # 升级前的旧记录：本次建立时间基线（大小明显不符说明下载后又更新过）
            if not exists:
                return "fresh", "记录在但本地文件缺失，重新下载"
            if _size_mismatch(rec_bytes, size_hint):
                return "update", "平台大小与旧记录不符，重新下载"
            return "skip_record", "下载记录命中"
        if not exists:
            return "fresh", "记录在但本地文件缺失，重新下载"
        return "skip_record", "下载记录命中"

    if not exists:
        return "fresh", ""
    if remote_epoch is not None:
        if local_mtime < remote_epoch:
            return "update", (f"本地文件较旧：{_fmt_time(local_mtime)}"
                              f"（平台 {_fmt_time(remote_epoch)}）")
        if local_mtime == remote_epoch:
            return "skip_exist", "本地文件已存在（时间与平台一致）"
        return "skip_exist", "本地文件较新，不覆盖"
    if _local_file_matches(dest, node.size_text):
        return "skip_exist", "本地文件已存在"
    return "fresh", ""


def _probe_remote_mtime(ses, course, node, referer):
    """DOM 未解析出平台时间时的回退：取 cldisk 直链响应头 Last-Modified。失败返回 None。"""
    direct, _reason = resolve_direct_url(ses, course, node, referer)
    if not direct:
        return None
    try:
        resp = ses.head(direct, headers={"Referer": f"{config.MOOC1}/"})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        return int(parsedate_to_datetime(resp.headers.get("last-modified", "")).timestamp())
    except (TypeError, ValueError):
        return None


def resolve_direct_url(ses, course, node, referer: str):
    """GET downloadData（不跟随重定向）→ (cldisk 签名直链, 其 Set-Cookie)；失败返回 (None, 原因)。"""
    url = (f"{config.DOWNLOAD_DATA}?dataId={node.data_id}&classId={course.clazz_id}"
           f"&cpi={course.cpi}&courseId={course.course_id}&ut=s")
    resp = ses.client.get(url, headers={"Referer": referer})
    if resp.status_code in REDIRECT_CODES:
        loc = resp.headers.get("location", "")
        if not loc:
            return None, "downloadData 重定向缺少 Location"
        return urljoin(str(resp.url), loc), dict(resp.cookies)
    return None, f"downloadData 未返回重定向（HTTP {resp.status_code}）"


def _try_stream(ses, url: str, headers: dict = None, cookies: dict = None,
                dest_part: Path = None, probe_limit: int = 1 << 20,
                progress=None, cancelled=None):
    """尝试流式请求直链。返回 (字节数, 状态描述)；被拒绝返回 (None, 描述)。

    dest_part 为 None 时仅探测（读最多 probe_limit 字节即断开）。
    progress(written, total)：落盘时按 chunk 上报（total 取 Content-Length，未知为 0）。
    cancelled：单元素列表标志；chunk 间命中则置位并返回 (None, "已取消")。
    """
    try:
        with ses.client.stream("GET", url, headers=headers or {}, cookies=cookies) as r:
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or "text/html" in ctype:
                return None, f"HTTP {r.status_code} {ctype.split(';')[0]}"
            if dest_part is None:
                total = 0
                for chunk in r.iter_bytes(65536):
                    total += len(chunk)
                    if total >= probe_limit:
                        break
                return total, "探测成功"
            total_len = int(r.headers.get("content-length") or 0)
            total = 0
            dest_part.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_part, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    if cancelled and cancelled[0]:
                        return None, "已取消"
                    f.write(chunk)
                    total += len(chunk)
                    if progress:
                        progress(total, total_len)
            return total, "OK"
    except httpx.HTTPError as e:
        return None, f"网络错误：{type(e).__name__}"


def download_course(ses, course, files, storage, referer: str, report: DownloadReport,
                    root: Path = None, on_result=None, on_progress=None, should_stop=None) -> list:
    """顺序下载文件列表（files 为 MaterialNode 列表），返回 DownloadResult 列表。

    时间戳校验：每文件先按「平台上传时间 vs 本地基线」决策（_plan_action）——
    已是最新跳过；平台较新直接覆盖（updated）；本地较新不覆盖。
    root：下载根目录（默认 config.DOWNLOAD_ROOT）。
    on_result(node, result)：每条结果即时回调（GUI 转发信号用）。
    on_progress(node, written, total)：当前文件流式进度（total 取 Content-Length，未知为 0）。
    should_stop()：取消检查——文件间命中则其余记 cancelled；流内命中则放弃当前文件。
    """
    root = root or config.DOWNLOAD_ROOT
    results: list = []

    def emit(node, result):
        results.append(result)
        if on_result:
            on_result(node, result)

    cancelled_flag = [False]

    def finish_remaining(reason: str):
        for rest in pending:
            emit(rest, DownloadResult(rest.relative_path, "cancelled", reason))

    pending = list(files)
    cleanup_part_files(root)
    best = None  # 记忆首个成功的尝试标签
    while pending:
        if should_stop and should_stop():
            cancelled_flag[0] = True
        if cancelled_flag[0]:
            finish_remaining("已取消")
            break
        node = pending.pop(0)
        rel = node.relative_path
        if not node.data_id:
            emit(node, DownloadResult(rel, "failed", "缺少 dataId"))
            continue
        if node.special:
            emit(node, DownloadResult(rel, "forbidden", "特殊目录"))
            continue
        if not node.is_down:
            emit(node, DownloadResult(rel, "forbidden", "教师未开放下载（isdown=0）"))
            continue

        # ---- 时间戳校验：平台上传时间 vs 本地基线（记录 remote_mtime / 本地 mtime）----
        dest = _final_path(root, course.name, rel)
        rec = storage.get_record(course.course_id, rel)
        remote_epoch = node.remote_mtime
        if remote_epoch is None and (rec is not None or dest.exists()):
            remote_epoch = _probe_remote_mtime(ses, course, node, referer)  # DOM 无时间时的回退
        action, decision = _plan_action(node, dest, rec, remote_epoch)

        if action == "skip_record":
            if remote_epoch is not None and rec is not None and rec["remote_mtime"] is None:
                storage.update_baseline(course.course_id, rel, remote_epoch)  # 旧记录回填基线
            emit(node, DownloadResult(rel, "skip_record", decision))
            continue
        if action == "skip_exist":
            if remote_epoch is None:
                storage.mark_done(course.course_id, rel, dest,
                                  parse_size_text(node.size_text) or dest.stat().st_size)
            elif int(dest.stat().st_mtime) == remote_epoch:   # 本地=平台文件：补建记录+基线
                storage.mark_done(course.course_id, rel, dest, dest.stat().st_size, remote_epoch)
            emit(node, DownloadResult(rel, "skip_exist", decision))
            continue
        if action == "fresh" and dest.exists():
            dest = _dedupe(dest)

        direct, set_cookies = resolve_direct_url(ses, course, node, referer)
        if not direct:
            emit(node, DownloadResult(rel, "failed", set_cookies))
            continue

        # ---- cldisk 直链请求头实验矩阵 ----
        attempts = [
            ("A 裸请求(无Referer)", {}, None),
            ("B Referer=mooc1", {"Referer": f"{config.MOOC1}/"}, None),
            ("C Referer+Set-Cookie", {"Referer": f"{config.MOOC1}/"}, set_cookies),
        ]
        if node.loadurl.startswith(("http://", "https://")):
            attempts.append(("D loadurl直链", {}, None))
        if best is not None:
            # 已有成功策略：优先复用，减少后续文件的多余探测
            attempts.sort(key=lambda a: 0 if a[0] == best else 1)

        part = dest.with_suffix(dest.suffix + ".part")
        written = None
        for label, headers, cookies in attempts:
            if cancelled_flag[0]:
                break
            written, note = _try_stream(
                ses, direct, headers, cookies, part,
                progress=(lambda w, t, _n=node: on_progress(_n, w, t)) if on_progress else None,
                cancelled=cancelled_flag if should_stop else None)
            if on_progress:
                on_progress(node, 0, 0)  # 本文件流结束：进度归零，避免残留旧值
            report.header_experiment.append((rel, label, note, "成功" if written is not None else "拒绝"))
            if written is not None:
                best = label
                report.best_strategy = label
                break
            if cancelled_flag[0]:
                break
        if written is None:
            part.unlink(missing_ok=True)
            emit(node, DownloadResult(
                rel, "cancelled" if cancelled_flag[0] else "failed",
                "已取消" if cancelled_flag[0] else "cldisk 直链全部头部尝试失败"))
        else:
            os.replace(part, dest)   # 覆盖式落盘（updated 场景目标文件已存在）
            if remote_epoch is not None:
                os.utime(dest, (remote_epoch, remote_epoch))  # 本地文件时间=平台上传时间
            storage.mark_done(course.course_id, rel, dest, written, remote_epoch)
            if action == "update":
                emit(node, DownloadResult(rel, "updated", decision, bytes_written=written))
            else:
                emit(node, DownloadResult(rel, "done", bytes_written=written))
        if not cancelled_flag[0]:
            time.sleep(random.uniform(*config.REQUEST_DELAY))
    report.results.extend(results)
    return results
