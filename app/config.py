# -*- coding: utf-8 -*-
"""全局常量与路径配置。

路径分两类：
- BASE_DIR：可写目录。开发模式 = 仓库根；PyInstaller 打包后 = exe 所在目录
  （data/、downloads/ 落在 exe 旁，随文件夹整体便携迁移）。
- ASSET_DIR：只读随包资源（图标/）。开发模式 = 仓库根/图标；打包后 = 包内 _internal/图标。
"""
import sys
from pathlib import Path

# ---------- 路径 ----------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    ASSET_DIR = Path(getattr(sys, "_MEIPASS", "")) / "图标" if getattr(sys, "_MEIPASS", None) else BASE_DIR / "图标"
else:
    BASE_DIR = Path(__file__).resolve().parents[1]
    ASSET_DIR = BASE_DIR / "图标"

DATA_DIR = BASE_DIR / "data"
EDGE_PROFILE = DATA_DIR / "edge_profile"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "mvp.db"
DOWNLOAD_ROOT = BASE_DIR / "downloads"
REPORT_PATH = BASE_DIR / "docs" / "MVP验证报告.md"

# ---------- 平台域名（2026-09-25 实测） ----------
LOGIN_PAGE = "https://eitech.mh.chaoxing.com/login"
MH_HOME = "https://eitech.mh.chaoxing.com/"
MOOC1 = "https://mooc1.chaoxing.com"
MOOC2ANS = "https://mooc2-ans.chaoxing.com"

COURSELISTDATA = f"{MOOC2ANS}/mooc2-ans/visit/courselistdata"
STUCOURSE_MIDDLE = f"{MOOC1}/visit/stucoursemiddle"
STU_DATALIST = f"{MOOC2ANS}/mooc2-ans/coursedata/stu-datalist"
DOWNLOAD_DATA = f"{MOOC1}/coursedata/downloadData"

# ---------- 请求配置 ----------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
REQUEST_DELAY = (1.0, 3.0)   # 每次请求前随机延迟区间（秒），拟人限速
HTTP_TIMEOUT = 30
LOGIN_TIMEOUT = 300          # 等待手动 CAS 登录超时（秒）

# ---------- 业务 ----------
# 默认目标课程（可被命令行 --course 覆盖；courseId/clazzId 运行时从课程列表匹配）
TARGET_COURSE_NAME = "计算机组成原理"
# 落盘结构：下载根目录/<课程名>/<relative_path>（2026-09-26 起不再建“资料”中间层）
# 资料区分页（2026-09-26 实测：pageSize=30；“当前页共 N 个”是每页条数而非总数）
PAGE_SIZE = 30
PAGES_PARAM = "pages"   # 参数名以 scripts/probe_pagination.py 实测为准
MAX_PAGES = 50
