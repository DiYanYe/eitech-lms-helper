# 东方理工 LMS 助手 · 开发方案（讨论稿 v0.2）

> 日期：2026-09-25
> **状态（2026-09-25 更新）**：MVP 已验证通过（登录/资料树/下载/作业全链路跑通）。平台接口实测结论以 `docs/接口实测文档.md` 为准（本文第 2、8 节的旧版假设部分已被实测修正）；工程现状见 `README.md`。
> 目标：开发一个**开源的**、可分发给同学使用的 Windows 桌面应用，**批量下载超星课程中的资料文件**（保留网页目录结构、跳过已下载），并在界面中**展示课程作业列表**。

---

## 1. 项目概述

| 项 | 内容 |
| --- | --- |
| 产品形态 | **仅 Windows** 桌面应用（GUI），打包为安装程序分发；暂不开发 macOS 版 |
| 目标用户 | 东方理工大学在校学生（非技术用户，要求双击即用） |
| 核心功能 | ① 课程资料批量下载（Word / PPT / PDF / 视频 / 音频），**保留网页"资料"区目录结构、已下载文件自动跳过**；② 作业列表在 UI 中展示（课程、作业名、截止时间、提交状态） |
| 不做的功能 | 自动答题、刷课时长、伪造学习记录、导出 Excel、m3u8/HLS 处理（资料中音视频均为直链） |
| 技术语言 | Python（开发者有 Python 基础） |
| 开源方式 | 源码公开（GitHub 主仓库 + Gitee 镜像，方便国内下载），协议建议 GPL-3.0 |

---

## 2. 平台与登录机制（2026-09-25 实测）

### 2.1 平台构成

- 学校门户：`https://lms.eitech.edu.cn/`（超星 wisweb 门户，机构标识 `wfwfid=333892`）
- 实际教学平台：`https://eitech.mh.chaoxing.com`（超星"一平三端"mh 域名）
- 课程内容页：`https://mooc1.chaoxing.com/course/{courseId}.html`（未登录访问会跳转错误页）
- 平台资源域：`p.ananas.chaoxing.com`、`cs.ananas.chaoxing.com` 等

### 2.2 登录链路（学校统一身份认证 CAS，无二次认证）

```
应用点击"登录" → DrissionPage 启动系统 Edge（专用持久化目录）
  │  打开 https://eitech.mh.chaoxing.com/login
  ▼
学校统一身份认证
  │  https://authserver.eitech.edu.cn/authserver/login?
  │    service=https://eitech.mh.chaoxing.com/sso/login/3rd/333892?refer=...
  │  （用户手动输入学号/密码，无短信/扫码等二次认证）
  ▼
CAS 回调
  │  https://eitech.mh.chaoxing.com/sso/login/3rd/333892
  ▼
登录成功：服务器向 .chaoxing.com 域下发 Cookie
  关键 Cookie：vc3（HttpOnly，核心凭证）、_uid、fid、lv、_d、uf、vc2 等
  程序经 CDP page.cookies() 取回全部 Cookie（含 HttpOnly），注入 HTTP 客户端
```

### 2.3 登录方案结论

- **不模拟登录接口**：密码有加密处理，且存在验证码/行为风控，学校 CAS 无法用接口模拟。
- **采用「DrissionPage 独立 Edge 窗口手动登录 + 持久化 user-data 目录」**：用户只在首次（或 Cookie 失效时）登录一次；程序通过 CDP 读取 Cookie（含 HttpOnly 的 vc3），全程不接触账号密码。
- Edge 为 Windows 10/11 系统自带，无需随包捆绑浏览器；若检测到 Edge 不可用，回退提示使用系统 Chrome。

---

## 3. 技术选型

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 语言 | **Python 3.11+** | 开发者有基础；采集、解析、自动化生态最成熟；开源参考最多 |
| GUI 框架 | **PySide6（Qt）** | 控件丰富（树、表格、进度条）；LGPL 协议允许分发；**不引入 QtWebEngine**，控制包体积 |
| 浏览器自动化 | **DrissionPage** | 经 CDP 控制**系统 Edge**（`set_browser_path(edge=True)`）；`cookies()` 可读 HttpOnly；`set_user_data_path()` 持久化登录态；自带下载管理（多线程、自动重连、自动同步 Cookie） |
| HTTP 客户端 | **httpx**（或直接用 DrissionPage 内置下载） | Cookie 注入、流式下载、超时重试、并发支持 |
| HTML 解析 | **BeautifulSoup4 + lxml**（或 parsel） | 解析课程/资料/作业页面 |
| 本地缓存 | **SQLite**（标准库 sqlite3） | 缓存课程、资料目录树、作业、下载记录，支持跳过已下载与快速展示 |
| 打包 | **PyInstaller（--onedir）+ Inno Setup** | 生成带图标的 setup.exe；无需附带浏览器内核与 ffmpeg，安装包显著更小；Nuitka 作为减小杀软误报的备选 |
| 自动更新 | 版本号 JSON + GitHub/Gitee Releases | 启动检查更新，接口变动后可快速发版 |

> 已确认资料区视频/音频为**普通直链文件**，不使用 m3u8，因此**不需要 ffmpeg**。

---

## 4. 总体架构

分三层：

- **UI 层（PySide6）**：登录引导、课程资料页、作业列表页、设置/关于。
- **业务服务层**：课程服务、资料服务、作业服务、下载管理器。
- **核心能力层**：DrissionPage 浏览器桥（Edge + 持久化目录 + Cookie 提取）、httpx 客户端、SQLite 缓存。

数据流：

```
登录按钮 → DrissionPage 启动 Edge（专用 user-data 持久化）
              │ 用户手动 CAS 登录
              ▼
        CDP 取回 Cookie（含 vc3）
              │
              ▼
          httpx 客户端
              │
   ┌──────────┼──────────────┐
   ▼          ▼              ▼
课程/资料接口  作业接口      文件直链下载
   │          │              │
SQLite 缓存  SQLite 缓存   下载管理器（限速/重试/续传）
   │          │              │
资料树(勾选) 作业表格 UI   按网页目录树落地的本地文件
```

---

## 5. 工程目录结构（建议）

```
eitech-lms-assistant/
├── app/
│   ├── main.py                     # 程序入口
│   ├── config.py                   # 平台常量（mh 域名、CAS 模板、wfwfid=333892）、用户配置
│   ├── models.py                   # 数据模型：Course / MaterialNode / Homework / DownloadTask
│   ├── ui/
│   │   ├── main_window.py          # 主窗口、顶部登录状态栏
│   │   ├── login_dialog.py         # 登录引导对话框（提示 + 调用浏览器桥）
│   │   ├── materials_tab.py        # 课程资料页（目录树 + 勾选 + 进度）
│   │   ├── homework_tab.py         # 作业列表页（表格）
│   │   ├── settings_dialog.py      # 设置
│   │   └── widgets/                # 进度条、通用对话框
│   ├── core/
│   │   ├── browser.py              # DrissionPage 启动 Edge、持久化 user-data、Cookie 提取
│   │   ├── session.py              # httpx 客户端、Cookie 注入、会话健康检查
│   │   ├── api/
│   │   │   ├── courses.py          # 课程列表接口（适配层）
│   │   │   ├── materials.py        # “资料”区目录树与文件接口（适配层）
│   │   │   └── homework.py         # 作业接口（适配层）
│   │   ├── downloader.py           # 下载队列、并发、重试、断点续传、目录结构映射
│   │   └── storage.py              # SQLite 封装
│   └── utils/                      # 文件名清洗、日志、路径
├── assets/                         # 应用图标
├── build/
│   ├── app.spec                    # PyInstaller 配置
│   └── installer.iss               # Inno Setup 脚本
├── docs/
│   └── 接口抓包文档.md              # M0 阶段产出
├── LICENSE                         # GPL-3.0
├── requirements.txt
└── README.md                       # 安装使用说明、开源说明、免责声明
```

---

## 6. 模块详细设计

### 6.1 登录模块（login_dialog + browser）

- 点击"登录"后，DrissionPage 经 CDP 启动系统 Edge：
  - `ChromiumOptions().set_browser_path(edge=True)`；
  - `set_user_data_path()` 指向 `%AppData%/EitechLmsAssistant/edge_profile`（**专用持久化目录**，不与用户日常 Edge 冲突）；
  - 加启动参数抑制首次运行引导页、默认浏览器检查。
- Edge 打开 `https://eitech.mh.chaoxing.com/login`，用户手动完成学校 CAS 登录（无二次认证）。
- 后台轮询 `page.cookies(all_domains=True)`：**检测到 `vc3` 且页面 URL 回到 mh 域 → 判定成功**，提示"登录成功"并进入主界面（可保留或关闭 Edge 窗口）。
- 每次启动做会话健康检查（请求轻量接口）；失效（403/跳登录页）时顶部显示"请重新登录"。
- Cookie 属敏感凭证：不写日志、不展示；可选 keyring（Windows DPAPI）加密保存。
- 兜底：未检测到 Edge 时尝试系统 Chrome；都没有则提示安装。

### 6.2 课程服务（api/courses）

- 拉取在读课程：`courseId / classId / 课程名 / 教师 / 封面`。
- 候选接口（**M0 抓包核实**）：`https://mooc1.chaoxing.com/visit/courses/study?isAjax=true`（HTML 隐藏域含 courseId、classId）；mh 域若有 JSON 接口优先。
- 结果写入 SQLite。

### 6.3 资料服务（api/materials）——目录结构是重点

- 进入课程详情页 **"资料"** 分区，按网页中的**文件夹层级**解析为一棵目录树：
  - 每个节点记录：名称、类型（文件夹 / Word / PPT / PDF / 视频 / 音频）、大小、`objectId` 或下载 URL、**相对路径（relative_path）**。
  - 例：网页中 `课件/第1章/导论.pptx` → relative_path = `课件/第1章/导论.pptx`。
- 附件直链候选（**M0 核实**）：`https://cs.ananas.chaoxing.com/download/{objectId}`。
- 教师设置禁止下载的文件不强行获取（尊重平台权限）。

### 6.4 作业服务（api/homework）

- 按课程拉取作业：**课程、作业名、截止时间、提交状态**（可附带发布时间用于排序）。
- 状态以平台显示为准：未开始 / 待完成 / 已提交 / 已批改（取到什么用什么，不臆造）。
- 候选路径（**M0 核实**）：`mooc1.chaoxing.com/work/...`、`/api/work...`，或移动端 JSON 接口 `mooc1-api.chaoxing.com`。

### 6.5 下载管理器（downloader）

- 任务队列 + 信号量限流（默认并发 **2~3**，可设置）。
- 按资料节点的 **relative_path 原样映射**到本地：`下载目录/课程名/资料/课件/第1章/导论.pptx`，自动创建中间文件夹。
- **已下载跳过**（双重判断）：
  1. SQLite 下载记录中已标记完成；
  2. 目标路径文件已存在且大小一致。
  命中即跳过，不重复下载。
- httpx 流式下载到 `.part` 临时文件 → 完成后改名；支持 **Range 断点续传**；失败指数退避重试 3 次。
- 同名冲突自动加序号；文件名非法字符清洗。
- 提供"打开所在文件夹"；UI 展示总进度、单文件进度、速度、失败原因与"重试失败项"。
- 也可直接使用 DrissionPage 内置下载能力（自动同步 Cookie、多线程、自动重连），M0 后择一。

### 6.6 数据存储（SQLite）

- `courses(course_id, class_id, name, teacher, cover, last_sync)`
- `material_nodes(id, course_id, parent_id, name, node_type, size, object_id, url, relative_path, last_sync)`
- `homework(id, course_id, title, start_time, deadline, status, work_id, last_sync)`
- `downloads(id, node_id, course_id, relative_path, local_path, status, bytes_total, bytes_done, updated_at)`
- `meta(key, value)`（配置、版本、最近同步时间）

---

## 7. 功能清单与 UI 设计

**主窗口**：顶部登录状态条（姓名或"请登录"按钮、刷新、设置），下方两个标签页。

1. **课程资料页**
   - 左侧：课程列表（带搜索）。
   - 右侧：所选课程"资料"区**目录树**（按网页文件夹层级展示），节点含复选框、类型图标、大小、下载状态。
   - 底部：下载目录选择、"下载选中 / 全部下载"、整体进度条、任务明细（可取消/重试）。
2. **作业列表页**
   - 表格列：课程、作业名、发布时间、截止时间、提交状态。
   - 按课程/状态筛选、按截止时间排序；**已逾期未交标红、临近截止高亮**。
   - 双击行在浏览器打开对应作业页面。
3. **登录引导**：点击登录后弹出引导框（"即将打开 Edge，请完成登录…"），后台检测到 vc3 后自动变为成功状态。
4. **设置/关于**：下载目录、并发数、开机检查更新、版本、开源仓库链接、免责声明、问题反馈（Issues）。

---

## 8. M0 阶段：接口逆向（抓包）计划

平台接口会迭代，正式开发前先用 3~5 天完成抓包，产出 `docs/接口抓包文档.md`：

1. 用 DrissionPage 监听网络请求，或 Fiddler / mitmproxy，完整走一遍：登录 → 课程 → 资料（进入各层文件夹）→ 作业。
2. 记录每个接口：URL、方法、关键参数（courseId/classId/objectId/token/enc）、返回结构（HTML/JSON）、所需 Cookie。
3. 重点确认：
   - 在读课程列表接口；
   - "资料"区**文件夹层级**的获取方式（一次返回整棵树还是逐级 XHR）；
   - 文件直链规则；
   - 作业列表接口与状态字段枚举。
4. 接口调用收敛在 `core/api/` **适配层**，平台改版只改适配层。

---

## 9. 开源、打包与分发

### 9.1 开源

- GitHub 主仓库 + Gitee 镜像（国内访问/下载快）；协议建议 **GPL-3.0**（要求衍生作品同样开源，防止被闭源盗用）。
- 仓库包含：源码、LICENSE、README（含安装/使用截图）、接口抓包文档、Issues 反馈模板。
- 注意：**不提交任何同学的 Cookie、个人信息与学校内部数据**；`.gitignore` 排除 profile 目录与缓存。

### 9.2 打包分发

- PyInstaller `--onedir`（启动快、误报相对少），含应用图标；**无需附带浏览器内核与 ffmpeg**。
- Inno Setup 生成 `东方理工LMS助手_Setup_vx.x.exe`，含快捷方式与卸载项。
- 无代码签名时 SmartScreen 会提示"未知发布者"，README 附"仍要运行"说明；Nuitka 可降低杀软误报。
- 应用内置更新检查（读取 GitHub/Gitee 版本 JSON）；发布渠道：Gitee/GitHub Releases + 校内群。

---

## 10. 开发里程碑（业余时间估算）

| 里程碑 | 内容 | 预计 |
| --- | --- | --- |
| M0 | 抓包分析产出接口文档；搭建工程骨架与开源仓库 | 3~5 天 |
| M1 | DrissionPage 登录 + 会话持久化 + 课程列表跑通 | 1 周 |
| M2 | 资料目录树采集 + 下载器（目录结构映射、跳过已下载、单课程完整跑通） | 1.5 周 |
| M3 | 作业列表采集 + 表格 UI | 0.5~1 周 |
| M4 | 完整 GUI 打磨、异常处理、设置、日志 | 1 周 |
| M5 | 打包、安装程序、自动更新、5~10 人小范围内测后发布 | 1 周 |

**验收标准**：

- 首次登录后长期免重复登录，失效有明确提示；
- 所选课程资料**按网页目录结构**完整落地，中断可续传，已下载自动跳过；
- 作业列表字段与网页端一致，可筛选/排序；
- 干净的 Windows 机器上安装即用，无需 Python 环境与额外组件。

---

## 11. 风控与反爬应对策略

原则：**像正常用户一样访问，只做只读操作，触发风控后退避 + 人工验证，不硬闯。**

### 11.1 常见风控信号

- 异常状态码：**412 / 403 / 429**；页面跳转验证页或出现"环境异常"；要求滑块/人机验证；
- 签名失效：`enc`、`token` 等参数有时效，缺失或过期被拒；
- 频率超限：单位时间同接口请求过多，先弹验证，继续刷可能升级为账号临时限制。

### 11.2 事前：三道防线

1. **身份真实**：DrissionPage 控制真实 Edge（真实浏览器/TLS 指纹、真实 Cookie）；尽量让请求从页面上下文发出，Referer、UA 自动正确；不用代理池、不换 IP。
2. **节奏拟人**：并发 2~3，请求间随机间隔 1~3 秒；导航式访问（先开课程首页再进资料）；按课程分批；内置"保守/标准"模式。
3. **请求最少**：目录树与文件信息 SQLite 强缓存，只做增量同步；enc/token 从页面现取现用，不硬编码。

### 11.3 事后：熔断机制

- 下载器统一识别风控响应（412/403/429、验证页、"环境异常"文案）；
- 命中即**立即暂停队列、不立刻重试**，逐级加长退避（分钟级）；
- 由用户在弹出的 Edge 中**手动完成验证**，点击"已完成"后恢复；连续触发则当天停止；
- **不接打码平台、不自动批量过验证码、不伪造指纹**。

### 11.4 账号安全提示

没有方法能保证账号不被限制，风险载体是用户本人账号；默认慢速、只读，不碰学习行为/答题接口；分发说明中写清使用建议。

---

## 12. 风险与应对

| 风险 | 应对 |
| --- | --- |
| 平台接口改版 | 接口收敛适配层；内置更新；保留抓包文档快速修复 |
| 资料目录为逐级懒加载 | 采集时遍历全部文件夹节点；提示"正在解析目录" |
| Edge 被个别同学卸载/禁用 | 回退系统 Chrome；README 说明 |
| 触发平台风控（412/验证页） | 见第 11 节：限速、熔断退避、人工验证 |
| 教师设置禁止下载 | 尊重权限，不绕过 |
| 杀软误报 / SmartScreen 拦截 | onedir + Nuitka 备选；文档说明 |
| 开源后被滥用/二次打包 | GPL-3.0 协议；README 明确合规使用范围 |

---

## 13. 合规说明

- 仅访问和下载**本人账号有权限查看**的资料，限个人学习使用；
- 不传播、不上传版权课件，不用于商业用途；
- 不实现自动答题、刷课、伪造学习记录等功能；
- README 与"关于"页内置免责声明；分发前建议向学校信息化部门了解相关规定。

---

## 14. 已确认的决策记录

1. 学校统一身份认证**无二次认证**；
2. **仅开发 Windows 版**，暂不做 macOS；
3. 项目**开源**（GitHub + Gitee 镜像，GPL-3.0）；
4. 资料区音视频为**直链**，不做 m3u8/ffmpeg；
5. 下载**保留网页目录结构**，已下载文件**自动跳过**；
6. 登录采用 **DrissionPage 调用系统 Edge**（独立窗口 + 持久化目录）。
7. 反爬策略：**慢速拟人 + 强缓存 + 熔断退避 + 人工验证**，不做打码/代理/指纹伪造（见第 11 节）。

---

*下一步：从 M0（抓包）开始——先在浏览器中完整走查"资料"区目录与作业页，记录接口；随后搭建工程骨架与登录模块。*
