# AGENTS.md — 项目规则手册

## 环境与命令

- Python 一律使用 miniconda 环境 `eitech-lms`：`C:\Users\DIYAN\scoop\persist\miniconda3\envs\eitech-lms\python.exe`
- 运行前设 `$env:PYTHONDONTWRITEBYTECODE='1'`（避免对 conda 目录的写入被沙箱拦截）
- 语法/导入检查：`py_compile` 各模块；核心链路验证：`scripts\verify_mvp.py`（`--no-download` / `--course 名称` / `--max-files N`）；GUI：`python -m app.ui.main`
- 依赖已固定于 `requirements.txt`（DrissionPage 4.1.1.4 / httpx / bs4 / lxml / PySide6 6.11.2），不要随意升级 DrissionPage 小版本（4.1.x API：`ChromiumOptions.set_argument()`，**没有** `add_arg`）；构建期依赖独立在 `requirements-dev.txt`（pyinstaller/pillow），勿混入运行依赖
- 打包：`pyinstaller 东方理工LMS助手.spec --noconfirm`（eitech-lms 环境，产物 dist/ 压 zip 分发）；ico 由 `scripts/make_ico.py` 生成
- 路径两分（config.py，改路径相关代码必看）：`BASE_DIR` = 可写目录（frozen 时 exe 旁，data/downloads 落这），`ASSET_DIR` = 包内只读资源（图标/）；**写文件一律 BASE_DIR 系常量、读随包素材一律 ASSET_DIR**（原 PROJECT_ROOT 已删）
- 开源仓库：https://github.com/DiYanYe/eitech-lms-helper（main 分支；gh CLI 已登录账号 DiYanYe，git 身份同账号）；推 Gitee 镜像 / 发 Release 时复用 gh 与现有 spec

## 红线（违反即事故）

- **Cookie（含 vc3）不打印、不写日志、不入 git**；`data/`、`downloads/`、`docs/MVP验证报告.md`、`build/`、`dist/`、`.trae/` 均在 .gitignore，永远不要提交（新增敏感目录先补 .gitignore 再提交，勿背清单）
- **尊重平台权限**：`isdown=0`（教师未开放下载）不强行获取；`tch-courseware`（教师课件）按产品决策不遍历不下载
- **风控安全**：请求间随机延迟 1~3s（`config.REQUEST_DELAY`）不可删除；只读操作；命中 412/403/429 立即停，不自动硬闯
- 平台接口细节以 `docs/接口实测文档.md` 为准（2026-09-26 更新，含分页实证）；开源资料里的旧版接口（mooc1/coursedata、ananas 直链、ananas/status）已失效，不要照搬

## core 层坑速查（改 app/core 前过一遍）

- **“当前页共 N 个”是每页条数，不是该层总数**——曾据此误判“全量无分页”；分页以层内 `totalPages` 隐藏域为准（`materials._fetch_paged`）
- 子层解析必须传 `parent_path` 前缀，否则 relative_path 丢目录、下载平铺（曾致 72 文件回归）
- cldisk 签名直链必须带 `Referer: https://mooc1.chaoxing.com/`；三个 enc（stuenc/coursedata/work）互相独立，均在 `docs/接口实测文档.md`

## PySide6 坑速查（写 UI 前过一遍）

- QMainWindow 必须显式 `setCentralWidget`，否则整棵控件树被 GC（报 "Internal C++ object already deleted"）；`QUrl` 在 QtCore 不在 QtGui；`QButtonGroup` 用 `setExclusive()`（没有 `setExclusionPolicy`）
- 布局两侧 `addStretch()` 不要带 stretch 参数（带 1 会和内容 stretch 三分空间）；勾选状态唯一源是页面的 `_checked` 集合，树控件只作视觉呈现
- `CheckTree` 接管 mouseReleaseEvent：箭头区判定是 `pos.x() < visualItemRect(item).x()`（该矩形已排除缩进槽，勿再叠加层数阈值，否则复选框点击被误转发原生 toggle）
- GUI 数据契约（2026-09-26 接入真实后端）：页面缓存一律按 **course_key**（`courseId|clazzId`，同名多班级可共存）；树/作业为异步渐进装载（`set_courses(courses)` + `set_course_roots(key, roots, error)` + `begin_load_if_needed` 闸门），**未选课程零请求**（选课持久化 QSettings key `courses/selected`）；`Storage`（sqlite）必须在 DownloadWorker.run() 内创建，禁止跨线程复用连接；worker 停止接口不强制统一（单发短任务如 CourseListWorker 无 request_stop），teardown 以 `getattr(w, "request_stop", None)` 探测 + 未停线程 terminate 兜底（防退出时 QThread 运行中被销毁 qFatal）
- 复选框/滚动条必须显式 QSS（theme.py 已内置）：Fusion 默认的 indicator 在对话框内渲染为黑方块、QScrollBar 是粗矩形；勾选态图 = `图标/勾选-白.svg`，经 theme.py 的 `%%CHECK%%` 占位替换注入绝对路径（文件缺失退化为纯红底）
- 树/表格卡片 `border-radius: 14px` 会被方形 `QHeaderView::section` 盖住左上/右上角。**两条死路已实测**：QSS `::section:first/:last` 圆角在 Qt 6 不生效；`paintSection` 里 `setClipPath` 会被样式引擎 drawControl 内的 ReplaceClip 重置。**唯一可靠修法 = `widgets.RoundedHeader` 用 `setMask`（部件级遮罩，绘制系统强制、不受 painter 裁剪重置影响）**，radius=外圆角−边框宽=13；带表头的卡片视图统一 `setHeader/setHorizontalHeader(RoundedHeader(...))`。取证技巧：`widget.render()` 到品红底 QImage 再 10x 放大四角，方形覆盖一目了然（`grab()` 会不透明填白，看不出透明区）
- 样式/交互改动以 `docs/ui-demo.html` 为基准；改完用 offscreen + `WA_DontShowOnScreen` 截图自检（offscreen 平台 CJK 显示为方块，须用 windows 平台才出真实字体）
- offscreen 平台下程序退出时 QSystemTrayIcon 会触发 0xC0000409 崩溃伪像（输出已完整、仅退出码异常）——托盘相关冒烟脚本用 `os._exit(0)` 收尾或忽略退出码；windows 平台正常
- 托盘菜单圆角必须透明三件套（同 widgets.py CourseMenu）：`FramelessWindowHint + NoDropShadowWindowHint + WA_TranslucentBackground`，缺一件就露出系统矩形底
- 托盘化（窗口隐藏）后退出不能依赖 `self.close()`——`lastWindowClosed` 只在**可见**窗口被关闭时触发，隐藏窗口 close 后进程不退出；托盘「退出」必须显式 `_teardown()` + `QApplication.quit()`（main_window._quit_app）

## 深入文档

| 文档 | 内容 |
| --- | --- |
| `docs/接口实测文档.md` | 平台接口逆向结论：链路、三个 enc、cldisk Referer 要求、行 schema |
| `docs/ui-demo.html` | 前端样式与交互定稿（单文件 HTML，浏览器直接打开；UI 改动以它为基准） |
| `东方理工LMS助手-开发方案.md` | 原始方案讨论稿（v0.2，M0 前的规划，部分已被实测推进） |
| `docs/MVP验证报告.md` | MVP 运行产物（个人数据，不入库） |

## 已定产品决策

- v1 范围仅"资料"区下载 + 作业展示；"章节"内容留 v1.1
- "教师课件"（tch-courseware）不做
- 下载保留网页目录结构（落盘 = 下载根/课程名/相对路径，**不自建「资料」中间层**），已下载（记录/本地文件）跳过；注意：历史旧文件在 `下载根/课程名/资料/` 下，记录键未变会跳过、不自动迁移
- 登录：DrissionPage + 真 Edge + 手动 CAS；Cookie 缓存 `data/cookies.bin`（Windows DPAPI CurrentUser 加密，ctypes 直调，见 `app/core/secret_box.py`；旧明文 cookies.json 首次加载自动迁移删除；跨机器拷贝不可解 → 回退重登录）
- UI（2026-09-26 定稿）：VI 标准色 `#92071C` + 辅助 `#FDB837`/`#AAA9A1`，三色语义（红=需行动/禁止，琥珀=进行中，灰=完成）；导航仅"资料下载/下载管理/作业列表"，登录页不常驻；"浏览器打开"与双击作业**直接跳系统浏览器不弹窗**；资料树行点击即勾选；下载目录走系统目录对话框（QSettings 持久化，key `download/dir`）
- 数据加载（2026-09-26 定稿）：登录后仅拉课程列表；「管理课程」（CoursePicker 菜单底部入口）勾选关注课程并持久化；已选课程作业每次启动自动后台拉取、资料树选中时才拉；未选课程自始至终零网络请求；会话失效统一回登录页，风控（412/403/429）立即停止不重试
- 作业列表按状态分组：未交 → 待批阅 → 已提交 → 其他（未知状态殿后），未交置顶；分组头跨 4 列、禁选禁双击（homework_page._GROUP_ORDER）
- 启动自动登录（2026-09-26）：`MainWindow.__init__` 调 `login_page.start_auto()`——LoginWorker(auto=True) 仅尝试本地 Cookie 缓存（不弹浏览器）；命中即直接进资料页并走课程列表流程，未命中/失效留在登录页引导手动登录（失效缓存的清除由既有 session_expired 链路兜底）
- 手动登录/重新登录（2026-09-26）：点登录页按钮 = LoginWorker(auto=False) **忽略缓存、必弹浏览器**（用户语义：重新登录就是强制重登，比如换账号）；只有启动自动登录读缓存
- 系统托盘与关闭行为（2026-09-26）：点 × 弹 CloseConfirmDialog 询问（「最小化到托盘」为默认按钮，可勾选记住 → QSettings key `close/action`，值 ask/tray/exit）；托盘常驻，左键/双击恢复窗口，右键菜单「显示主窗口 / 关闭行为三选一（互斥）/ 退出」；仅拦截 ×，最小化按钮不变；托盘/窗口图标走 `icons.app_icon()`——`图标/logo.png|ico|svg` 存在即优先加载，否则绘制 VI 红占位兜底（现役 logo 为 512×512 裁剪版）
- 打包分发（2026-09-26 定稿）：便携 zip 路线——PyInstaller onedir + windowed（不用 onefile：启动慢、杀软误报高；不启用 UPX）；spec 提交入库，`使用说明.txt` 由 spec 末尾 shutil.copy2 复制到 exe 旁（datas 目标 `.` 在 onedir 下落 `_internal/`，同学看不到，不能依赖 datas）；Edge/Python 不打包（`find_edge()` 系统检测）；Inno Setup 留作后续可选项（复用 ico/spec）
