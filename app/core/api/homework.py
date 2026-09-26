# -*- coding: utf-8 -*-
"""作业列表适配层（新版 mooc2/work/list 页面）。

依据 2026-09-25 实测：
- 入口：study 页 HTML 内 iframe URL（含 work-enc）
- 条目：li[data=work/task URL]；标题 p.overHidden2；状态 p.status；时间 div.time
- 状态枚举实测：未交 / 待批阅（其余以平台显示为准，取到什么用什么）
"""
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.core.session import ChaoxingSession
from app.utils import clean_text


@dataclass
class Homework:
    title: str
    status: str
    time_text: str      # 平台原文，如“剩余124小时44分钟”
    task_url: str       # 作业详情页 URL（含 workId/answerId/enc），可用于浏览器打开


def fetch_homework(ses: ChaoxingSession, work_list_url: str) -> list:
    if not work_list_url:
        return []
    resp = ses.get(work_list_url,
                   headers={"Referer": "https://mooc2-ans.chaoxing.com/"})
    soup = BeautifulSoup(resp.text, "lxml")
    items: list = []
    for li in soup.select("li[data]"):
        data = li.get("data", "") or ""
        if "/work/task" not in data:
            continue
        p_title = li.select_one("p.overHidden2")
        p_status = li.select_one("p.status")
        div_time = li.select_one("div.time")
        items.append(Homework(
            title=clean_text(p_title.get_text() if p_title else ""),
            status=clean_text(p_status.get_text() if p_status else ""),
            time_text=clean_text(div_time.get_text() if div_time else ""),
            task_url=data,
        ))
    return items
