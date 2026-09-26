# 东方理工 LMS 助手（MVP）

面向宁波东方理工大学学生的超星平台辅助工具：**批量下载课程"资料"区文件**（保留网页目录结构、已下载自动跳过）并**整合课程作业信息**。仅支持 Windows。

> 当前状态：核心链路 MVP 验证通过（2026-09-25）；**PySide6 图形界面已完成并接入真实后端**（2026-09-26，登录 / 课程列表 / 资料树 / 下载 / 作业全链路走真实平台接口）。

## 功能（当前 MVP）

**核心链路（已实测）**

- 系统一键登录学校统一身份认证（CAS），Cookie 本地缓存复用
- 拉取全部在读/历史课程列表
- 递归采集课程"资料"区目录树（含文件夹层级、文件类型/大小/下载权限）
- 按网页目录结构落盘下载：`downloads/<课程名>/<文件夹>/<文件>`（课程文件夹下直接放资料文件）
- 已下载自动跳过（SQLite 记录 + 本地文件双重判断）
- 拉取作业列表（标题 / 提交状态 / 剩余时间 / 详情链接）

**图形界面（PySide6，真实后端）**

- 登录引导作为启动主界面：启动即自动尝试本地缓存登录（不弹浏览器），未命中时点击按钮打开真实 Edge 手动 CAS 登录（“重新登录”同样强制开浏览器）；登录成功自动进入资料下载
- 「管理课程」勾选需要关注的课程（QSettings 持久化）：仅已选课程发起请求——作业每次启动自动后台拉取，资料树选中课程时按需加载，未选课程零请求
- 资料下载页：课程切换、全选 / 行点击勾选、文件夹三态联动、"浏览器打开"跳转课程资料页、自定义下载目录（系统对话框 + 配置持久化）
- 下载管理：真实下载进度（Content-Length 已知显示百分比，未知显示忙碌）、统计卡片、取消（当前文件写完即停）；作业列表：状态着色、双击跳转浏览器作业页
- 系统托盘常驻：点 × 弹窗选择「最小化到托盘 / 完全退出」（可记住选择不再询问），下载进行中最小化到托盘后台继续；托盘左键/双击恢复窗口，右键菜单退出
- 校园 VI 配色（标准色 `#92071C` + `#FDB837` / `#AAA9A1`），文件类型彩色图标（`图标/` 目录 SVG）

不做：自动答题、刷课时长、伪造学习记录、绕过教师下载权限。

## 环境要求

- Windows 10/11 + 系统自带 Microsoft Edge
- Python 3.12（本项目使用 miniconda 环境 `eitech-lms`）
- 依赖见 `requirements.txt`（DrissionPage / httpx / beautifulsoup4 / lxml / PySide6）

## 快速开始

```powershell
# 使用 eitech-lms 环境（按需替换为自己的解释器路径）
$env:PYTHONDONTWRITEBYTECODE='1'

# 图形界面（真实登录 + 真实下载）
C:\Users\DIYAN\scoop\persist\miniconda3\envs\eitech-lms\python.exe -m app.ui.main

# 核心链路 CLI 验证（真实登录）
C:\Users\DIYAN\scoop\persist\miniconda3\envs\eitech-lms\python.exe scripts\verify_mvp.py            # 完整验证（登录后自动下载"计算机组成原理"）
C:\Users\DIYAN\scoop\persist\miniconda3\envs\eitech-lms\python.exe scripts\verify_mvp.py --no-download   # 只验证链路
```

- 首次运行会弹出 Edge 窗口，手动完成学校 CAS 登录即可；Cookie 缓存于 `data/cookies.bin`（**Windows DPAPI 当前用户加密**，仅本机本用户可解密，已加入 .gitignore，切勿提交或外传）
- 验证报告输出到 `docs/MVP验证报告.md`（含个人课程信息，同样不入库）

## 打包分发（构建免安装便携包）

构建机执行（使用者无需 Python 环境，解压即用）：

```powershell
pip install -r requirements-dev.txt           # 构建期依赖（pyinstaller / pillow，与运行依赖分离）
python scripts\make_ico.py                    # 图标/logo.png → 图标/logo.ico（logo 变更时重跑）
pyinstaller 东方理工LMS助手.spec --noconfirm   # 产物：dist/东方理工LMS助手/
```

将 `dist/东方理工LMS助手/` 整个文件夹压缩为 zip 即可分发。使用者侧：解压到任意**可写**目录（勿放 Program Files），双击 `东方理工LMS助手.exe`，需 Win10/11 + 系统 Edge；随包根的 `使用说明.txt` 是面向使用者的完整说明。运行数据（`data/`、`downloads/`）生成在 exe 旁，随文件夹整体迁移；Cookie 经 DPAPI 加密、不跨机器生效，每位使用者各自登录。

## 工程结构

```
app/
├── config.py               # 平台常量、路径、限速参数
├── utils.py                # 文件名清洗、大小解析、日志
├── core/
│   ├── browser.py          # DrissionPage 启动 Edge + CAS 登录 + Cookie 导出/缓存
│   ├── session.py          # httpx 会话：Cookie 注入、限速、风控识别、重试
│   ├── secret_box.py       # Windows DPAPI 加密封箱（Cookie 落盘加密）
│   ├── storage.py          # SQLite 下载记录
│   ├── downloader.py       # 下载器：downloadData → cldisk 直链、跳过逻辑
│   └── api/                # 平台接口适配层（改版只改这里）
│       ├── courses.py      # 课程列表 + 学习页 enc 提取
│       ├── materials.py    # 资料树递归采集
│       └── homework.py     # 作业列表解析
└── ui/                     # PySide6 图形界面（样式基准：docs/ui-demo.html）
    ├── main.py             # 入口：python -m app.ui.main
    ├── main_window.py      # 侧边导航 + 页面装配
    ├── theme.py            # VI 配色 QSS + 状态语义
    ├── icons.py            # 文件类型 SVG 图标 + 应用图标（图标/logo.* 优先，缺省绘制占位）
    ├── widgets.py          # 导航徽标、课程选择器、Toast 等通用件
    ├── workers.py          # QThread：登录 / 课程列表 / 作业 / 资料树 / 下载
    ├── dialogs.py          # 课程管理 / 关闭确认对话框
    └── pages/              # 登录引导 / 资料下载 / 下载管理 / 作业列表
图标/                        # 应用 logo.png/.ico + 文件类型彩色 SVG 素材（UI 与 Demo 同源）
scripts/verify_mvp.py       # MVP 验证入口（CLI）
scripts/probe_pagination.py # 资料区分页探针（逐层对账 / --scan-all 全量深扫）
scripts/make_ico.py         # 构建期工具：logo.png → 多尺寸 logo.ico
东方理工LMS助手.spec         # PyInstaller 打包配置（onedir + windowed，提交入库可复现）
requirements-dev.txt        # 构建期依赖（pyinstaller/pillow；运行依赖见 requirements.txt）
使用说明.txt                 # 随包分发说明（构建时自动复制到 exe 旁）
docs/ui-demo.html           # 前端样式定稿（单文件 HTML，浏览器直接打开）
docs/接口实测文档.md          # 平台接口逆向结论（实现前必读）
```

## 合规与免责声明

- 仅访问和下载**本人账号有权限查看**的资料，限个人学习使用；不传播、不上传版权课件
- 教师设置禁止下载的文件（`isdown=0`）不强行获取；"教师课件"目录不做处理
- 不实现自动答题、刷课、伪造学习记录等任何写入行为
- 登录采用真实浏览器 + 手动输密码，程序不接触账号密码；请妥善保管本机 `data/` 目录
- 使用本工具产生的任何账号风险由使用者本人承担；分发前请了解学校相关规定

## Roadmap

- [x] PySide6 GUI 框架（资料树勾选、下载管理、作业表格）
- [x] GUI 接入真实后端（2026-09-26：登录/课程列表/资料树/下载/作业全链路；「管理课程」选课制——未选课程零请求）
- [x] 资料区分页实证（2026-09-26：pageSize=30、翻页 `&pages=N`、总页数取 totalPages 隐藏域；按层精确翻页已实现）
- [x] Cookie 本地加密存储（2026-09-26：Windows DPAPI CurrentUser，ctypes 零依赖实现）
- [x] 系统托盘与关闭确认（2026-09-26：点 × 弹窗询问 + 记住选择 + 托盘菜单）
- [x] 便携打包分发（2026-09-26：PyInstaller onedir → `dist/东方理工LMS助手-v1.0.zip`，免安装解压即用）
- [ ] 开源发布（GitHub + Gitee，GPL-3.0；可选 Inno Setup 安装器，复用现有 ico/spec）

## 许可证

本项目以 [GPL-3.0](LICENSE) 许可证开源。
