# -*- coding: utf-8 -*-
"""课程列表与学习页（stuenc / work-enc 提取）适配层。

依据 2026-09-25 实测：
- 课程列表：POST mooc2-ans/visit/courselistdata（HTML）
- 课程入口：mooc1/visit/stucoursemiddle → 跳转 mycourse/stu?...&enc={stuenc}
- 作业 iframe：study 页 HTML 内 /mooc2/work/list?...&enc={work-enc}
"""
import re
import time
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app import config
from app.core.session import ChaoxingSession


@dataclass
class Course:
    course_id: str
    clazz_id: str
    cpi: str
    name: str


def course_key(course) -> str:
    """课程身份键：同名多班级课程可区分（GUI 缓存/选课持久化均用它）。"""
    return f"{course.course_id}|{course.clazz_id}"


def material_page_url(course) -> str:
    """课程资料页 URL（新版 stu-datalist，"浏览器打开"按钮跳转目标）。"""
    return (f"{config.STU_DATALIST}?courseid={course.course_id}"
            f"&clazzid={course.clazz_id}&cpi={course.cpi}&ut=s")


@dataclass
class StudyContext:
    stuenc: str          # 学习页 URL 中的 enc
    work_list_url: str   # 作业列表 iframe 完整 URL（内含 work-enc）
    final_url: str


def fetch_course_list(ses: ChaoxingSession) -> list:
    """拉取全部课程（含历史学期）。"""
    resp = ses.post(
        config.COURSELISTDATA,
        data={"courseType": "1", "courseFolderId": "0", "query": "", "superstarClass": "0"},
        headers={"Referer": f"{config.MOOC2ANS}/mooc2-ans/visit/interaction"},
    )
    soup = BeautifulSoup(resp.text, "lxml")
    courses: list = []
    global_cpi = ""
    for div in soup.select("div.course"):
        cid = div.select_one("input.courseId")
        clz = div.select_one("input.clazzId")
        if not (cid and clz):
            continue
        person = div.select_one("input.curPersonId")
        if person and person.get("value"):
            global_cpi = person["value"]
        courses.append(Course(
            course_id=cid.get("value", ""),
            clazz_id=clz.get("value", ""),
            cpi=person.get("value", "") if person else "",
            name=_course_name(div),
        ))
    # curPersonId 全员一致：单条缺失时用全局值补齐
    for c in courses:
        if not c.cpi:
            c.cpi = global_cpi
    return courses


def _course_name(div) -> str:
    """课程名提取：名称元素选择器在实测中未命中，优先试常见 class，退回文本切分。

    页面文本结构（实测）：课程名 / 班级：XXX / 学校 / 教师 / 开课时间：...
    """
    for sel in (".course-name", ".courseName", "h3"):
        el = div.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    lines = [ln.strip() for ln in div.get_text("\n").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.startswith("班级：") and i > 0:
            return lines[i - 1]
    return lines[0] if lines else "未知课程"


def open_study_page(ses: ChaoxingSession, course: Course) -> StudyContext:
    """经 stucoursemiddle 中间页进入学习页，提取 stuenc 并构造作业列表 URL。

    work-enc 来自学习页隐藏域 <input id="workEnc">（实测确认，不在跳转 URL 中）。
    work/list 完整 URL 参数与浏览器实测一致：
      ?courseId=&classId=&cpi=&ut=s&t={ms}&stuenc={stuenc}&enc={workEnc}
    """
    url = (f"{config.STUCOURSE_MIDDLE}?courseid={course.course_id}"
           f"&clazzid={course.clazz_id}&cpi={course.cpi}&ismooc2=1&v=2")
    resp = ses.get(url, headers={"Referer": f"{config.MOOC2ANS}/"}, follow_redirects=True)
    final_url = str(resp.url)
    m = re.search(r"[?&]enc=([0-9a-f]{32})", final_url)
    stuenc = m.group(1) if m else ""
    if not stuenc:
        # 兜底：学习页 HTML 内 iframe URL 也带 stuenc
        m = re.search(r"stuenc=([0-9a-f]{32})", resp.text)
        stuenc = m.group(1) if m else ""
    work_enc = ""
    m3 = re.search(r'id="workEnc"[^>]*value="([0-9a-f]{32})"', resp.text)
    if m3:
        work_enc = m3.group(1)
    work_list_url = ""
    if stuenc and work_enc:
        work_list_url = (f"{config.MOOC1}/mooc2/work/list?courseId={course.course_id}"
                         f"&classId={course.clazz_id}&cpi={course.cpi}&ut=s"
                         f"&t={now_ms()}&stuenc={stuenc}&enc={work_enc}")
    return StudyContext(stuenc=stuenc, work_list_url=work_list_url, final_url=final_url)


def now_ms() -> str:
    return str(int(time.time() * 1000))
