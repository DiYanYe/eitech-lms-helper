# -*- coding: utf-8 -*-
"""“资料”区目录树采集（新版 mooc2-ans/coursedata/stu-datalist 接口）。

依据 2026-09-25 实测：
- 根页面：stu-datalist?courseid=&clazzid=&cpi=&ut=s&stuenc=（完整 HTML）
- 文件夹遍历：同端点 XHR：&dataName=&dataId=&type=1&parent=&flag=0&enc={coursedata-enc}
  &microTopicId=0&isAjax=isAjax（URL 不变，AJAX 加载）
- 行结构：ul.dataBody_td，属性 type/id(=dataId)/dataname/objectid/loadurl/url/isdown；
  大小文本在 li.dataBody_size_stu；coursedata-enc 在 onclick=toOpen(...) 第 10 个参数
"""
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from bs4 import BeautifulSoup

from app import config
from app.core.session import ChaoxingSession

# toOpen('name','type',dataId,'loadurl','objectId','url',flag,source,'clazzid','enc','video_type','t','')
_TOOPEN_RE = re.compile(
    r"toOpen\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*'([^']*)'\s*,\s*(\d+)\s*,"
    r"\s*'((?:[^'\\]|\\.)*)'\s*,\s*'((?:[^'\\]|\\.)*)'\s*,\s*'((?:[^'\\]|\\.)*)'\s*,"
    r"\s*(\d+)\s*,\s*(\d+)\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
)
_TOTAL_RE = re.compile(r"当前页共\s*(\d+)\s*个")          # 注意：这是“每页条数”，不是该层总数
_TOTALPAGES_RE = re.compile(r'id="totalPages"[^>]*value="(\d+)"')  # 层 HTML 隐藏域，总页数

FOLDER_TYPE = "afolder"
SPECIAL_TYPES = {"tch-courseware"}  # “教师课件”目录：产品决策不下载，仅列出不遍历


@dataclass
class MaterialNode:
    name: str
    node_type: str            # afolder/pdf/pptx/docx/tch-courseware/mp4...
    data_id: str
    object_id: str
    is_down: bool             # 教师是否允许下载（isdown 属性；0=平台不提供下载按钮）
    size_text: str
    relative_path: str        # 相对“资料”根的路径（含文件名，/ 分隔）
    loadurl: str = ""
    url: str = ""
    special: bool = False
    children: list = field(default_factory=list)


@dataclass
class MaterialTree:
    nodes: list               # 展平的全部节点（含文件夹）
    coursedata_enc: str
    total_declared: int       # 根页第 1 页条数（“当前页共 N 个”是每页计数，非该层总数）
    todos: list
    totals_match: bool = True  # 各层分页完整性对账（False = 达 MAX_PAGES 未终止，可能漏文件）
    pagination_param: str = ""  # 翻页参数名（2026-09-26 矩阵实证：pages；总页数取层内 totalPages 隐藏域）
    roots: list = field(default_factory=list)  # 树形根节点（children 已挂好，GUI 直接渲染）


def root_url(course, stuenc: str) -> str:
    return (f"{config.STU_DATALIST}?courseid={course.course_id}"
            f"&clazzid={course.clazz_id}&cpi={course.cpi}&ut=s&stuenc={stuenc}")


def _folder_url(base: str, folder: MaterialNode, enc: str) -> str:
    return (f"{base}&dataName={quote(folder.name)}&dataId={folder.data_id}"
            f"&type=1&parent=&flag=0&enc={enc}&microTopicId=0"
            f"&t={int(time.time() * 1000)}&isAjax=isAjax")


def _extract_html(resp_text: str) -> str:
    """遍历 XHR 响应可能是 HTML 片段或 JSON 包装，统一取出含 dataBody 的 HTML。"""
    text = (resp_text or "").strip()
    if "dataBody" in text:
        return text
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(obj, dict):
        for key in ("data", "html", "content", "result", "msg", "info"):
            val = obj.get(key)
            if isinstance(val, str) and "dataBody" in val:
                return val
        stack = list(obj.values())
        while stack:  # 兜底：深度搜第一个含标记的字符串
            cur = stack.pop()
            if isinstance(cur, dict):
                stack.extend(cur.values())
            elif isinstance(cur, str) and "dataBody" in cur:
                return cur
    return text


def _attr(attrs: dict, key: str, default: str = "") -> str:
    val = attrs.get(key, default)
    if isinstance(val, list):
        val = " ".join(val)
    return str(val).strip()


def parse_datalist(html: str, parent_path: str = ""):
    """解析资料列表 HTML → (节点列表, coursedata_enc)。"""
    soup = BeautifulSoup(html, "lxml")
    nodes: list = []
    enc = ""
    for ul in soup.select("ul.dataBody_td"):
        attrs = ul.attrs
        ntype = _attr(attrs, "type")
        data_id = _attr(attrs, "id")
        name = _attr(attrs, "dataname") or "未命名"
        is_down = _attr(attrs, "isdown", "1") == "1"
        size_li = ul.select_one("li.dataBody_size_stu")
        size_text = size_li.get_text(" ", strip=True) if size_li else ""
        object_id = loadurl = url = ""
        m = _TOOPEN_RE.search(str(ul))
        if m:
            loadurl = m.group(4).replace("\\'", "'")
            object_id = m.group(5).replace("\\'", "'")
            url = m.group(6).replace("\\'", "'")
            enc = enc or m.group(10)
        nodes.append(MaterialNode(
            name=name, node_type=ntype, data_id=data_id, object_id=object_id,
            is_down=is_down, size_text=size_text,
            relative_path=f"{parent_path}{name}",
            loadurl=loadurl, url=url, special=(ntype in SPECIAL_TYPES),
        ))
    return nodes, enc


def _fetch_paged(ses: ChaoxingSession, first_url: str, referer: str, parent_path: str = ""):
    """拉取一层的全部条目：第 1 页 + 按 totalPages 精确翻页。

    parent_path：子层调用时传入父目录前缀（保证 relative_path 保留目录结构）。
    返回 (nodes, enc, total_pages, complete)。
    - 翻页（2026-09-26 实证）：层 HTML 隐藏域 id="totalPages" 给出总页数，
      用 &pages=N 逐页取（pageSize=30）；totalPages 缺失时按满页兜底持续翻页
    - complete=False：达到 MAX_PAGES 仍未终止（调用方应告警，可能漏文件）
    """
    resp = ses.get(first_url, headers={"Referer": referer})
    html = _extract_html(resp.text)
    nodes, enc = parse_datalist(html, parent_path)
    m = _TOTALPAGES_RE.search(html)
    total_pages = int(m.group(1)) if m else 0
    seen = {n.data_id for n in nodes if n.data_id}
    complete = True

    def fetch_page(page: int):
        r = ses.get(f"{first_url}&{config.PAGES_PARAM}={page}",
                    headers={"Referer": referer})
        page_nodes, _ = parse_datalist(_extract_html(r.text), parent_path)
        new = [n for n in page_nodes if n.data_id and n.data_id not in seen]
        if new:
            seen.update(n.data_id for n in new)
            nodes.extend(new)
        return page_nodes, new

    if total_pages > 1:
        for page in range(2, min(total_pages, config.MAX_PAGES) + 1):
            _, new = fetch_page(page)
            if not new:
                break
        if total_pages > config.MAX_PAGES:
            complete = False
    elif len(nodes) >= config.PAGE_SIZE:
        # 兜底：无 totalPages 域但满页 → 持续翻页直到不满页 / 无新行
        page = 1
        while page < config.MAX_PAGES:
            page += 1
            page_nodes, new = fetch_page(page)
            if not new or len(page_nodes) < config.PAGE_SIZE:
                break
        else:
            complete = False
    return nodes, enc, total_pages, complete


def fetch_tree(ses: ChaoxingSession, course, stuenc: str) -> MaterialTree:
    """递归拉取整棵资料树（文件夹逐级 XHR + 按 totalPages 翻页 + 完整性对账）。"""
    base = root_url(course, stuenc)
    roots, enc, _, _ = _fetch_paged(ses, base, base)
    todos: list = []
    if not enc:
        todos.append("根页面未提取到 coursedata-enc（toOpen 解析失败）")
    totals_match = True

    all_nodes: list = []

    def walk(nodes: list):
        nonlocal totals_match
        for nd in nodes:
            all_nodes.append(nd)
            if nd.node_type == FOLDER_TYPE and nd.data_id and enc:
                children, _, _tp, complete = _fetch_paged(
                    ses, _folder_url(base, nd, enc), base,
                    parent_path=f"{nd.relative_path}/")
                nd.children = children
                if not complete:
                    totals_match = False
                    todos.append(f"文件夹“{nd.relative_path}”翻页达 MAX_PAGES 上限仍未终止，"
                                 f"可能漏文件（解析 {len(children)} 条）")
                walk(children)
            # tch-courseware（教师课件）：产品决策不下载，不遍历、不记待办

    walk(roots)
    return MaterialTree(nodes=all_nodes, coursedata_enc=enc,
                        total_declared=len(roots), todos=todos,
                        totals_match=totals_match, pagination_param=config.PAGES_PARAM,
                        roots=roots)
