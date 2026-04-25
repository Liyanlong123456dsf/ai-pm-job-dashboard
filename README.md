# AI PM Job Dashboard

> AI 产品经理岗位抓取 · 数据看板 · 一体化桌面应用（Windows + macOS）

![platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-blue)
![electron](https://img.shields.io/badge/electron-33-9feaf9)
![python](https://img.shields.io/badge/python-3.10%2B-yellow)
![license](https://img.shields.io/badge/license-MIT-green)

**在线看板**：<https://liyanlong123456dsf.github.io/ai-pm-job-dashboard/>

---

## 🚀 快速上手（最短路径）

### 1️⃣ 只想"看数据"
打开浏览器访问在线看板即可，无需安装任何东西。

### 2️⃣ 桌面应用（Electron 控制台 + 看板）
**Windows**：
```powershell
# 运行打包好的
release\AI-PM-Job-Dashboard-1.0.0-Windows-x64-Setup.exe   # 引导式安装

# 或源码启动（开发模式）
npm install
npm run start
```

**macOS**：
```bash
npm install
npm run start
# 或双击 launcher/start.command
```

应用启动后自带：
- 🎛 **控制台** — 4 个启动卡片（守护进程 / 单轮爬取 / 登录检查 / 飞书同步）
- 📊 **数据看板** — Bento 风格 7 Tab（总览 / 方向 / 薪资 / 城市 / 公司 / 岗位 / 深度分析）
- 📜 **日志** — 实时查看爬虫 stdout / stderr
- 🧩 **配置** — 关键词、城市、凭证
- 📈 **历史** — 每轮爬取记录
- ℹ️ **关于** — 版本、Python 状态、依赖检查

### 3️⃣ 纯命令行（服务器 / CI 无人值守）
```bash
# 全天候守护进程（循环爬取，崩溃自动重启）
python scripts/auto_daily.py

# 单轮爬取
python scripts/daily_update.py

# 快速验证（3-5 关键词）
python scripts/daily_update.py --quick
```

---

## 🕷 爬虫引擎

- **BOSS 直聘** — 基于 DrissionPage 的 API 拦截（监听 `joblist.json`）
- **50 关键词库** — 每月自动扩展，每轮随机抽取 5-8 个关键词
- **10 热门城市** — 杭州 · 上海 · 北京 · 深圳 · 厦门 · 成都 · 西安 · 广州 · 郑州 · 南京
- **持久化登录** — 首次手动登录后 Cookie 存储在 `.chrome_profile/`
- **强反封** — 随机延迟 · 模拟人类滚动 · 失败自动退避
- **智能去重** — 基于「职位名+公司名」MD5 哈希
- **自动清洗** — 失效链接检测 · 过期岗位清理 · 薪资结构化
- **失败恢复** — 超时重试 · 僵尸进程检测 · 热重载配置

---

## 📊 数据看板（Apple Dark 风格）

- **7 Tab 导航** — 总览 · 方向 · 薪资 · 城市 · 公司 · 岗位列表 · 深度分析
- **Bento 总览** — 大号 KPI + 7 日趋势柱图 + 城市/方向排行
- **薪资** — 档位分布 · 等级 vs 月薪 · 月薪区间
- **城市** — 柱图 · 方向热力图 · 城市对比
- **公司** — 招聘活跃度排行 + 平均薪资
- **岗位表** — 搜索过滤 · 双击跳转 BOSS
- **深度分析** — 技术栈频率 × 行业场景
- **5 分钟自动刷新** + **手动刷新按钮** + **visibilitychange 回 Tab 立即刷新**

---

## 🚦 自动化（守护进程）

Electron 控制台里点击 🚀 守护进程 → 启动，或命令行：
```bash
python scripts/auto_daily.py
```

守护进程自带：
- 全天候循环爬取，崩溃自动重启
- Git 自动推送 GitHub（含代理自动检测）
- 飞书同步到云文档
- 登录失败自动重试
- 防休眠（Windows `SetThreadExecutionState` / macOS `caffeinate`）

---

## 📦 项目结构

```
ai-pm-job-dashboard/
├── electron/                      # Electron 主进程
│   ├── main.js                    # 窗口管理 + Python 子进程桥接
│   └── preload.js                 # 渲染进程安全桥
├── app/                           # Electron 渲染进程（前端 UI）
│   ├── index.html                 # 控制台主界面（6 Tab）
│   ├── dashboard.html             # 数据看板（嵌入式）
│   ├── js/renderer.js             # 前端交互
│   └── styles/main.css            # 全局样式
├── job_dashboard.html             # 独立看板（GitHub Pages 用）
├── index.html                     # 重定向到 job_dashboard.html
│
├── scripts/                       # Python 后端
│   ├── auto_daily.py              # 全天候守护进程
│   ├── daily_update.py            # 单轮主流程
│   ├── monitor.py                 # 命令行监控
│   ├── login_check.py             # 登录状态检查
│   ├── sync_feishu.py             # 飞书同步
│   ├── gen_knowledge.py           # 知识库生成
│   ├── platform_utils.py          # 跨平台工具
│   └── spiders/
│       └── boss_dp.py             # BOSS 直聘爬虫
│
├── config/
│   ├── keywords.json              # 关键词库 + 城市 + 调度配置
│   └── cookies.json               # Cookie（.gitignore）
├── launcher/                      # Electron 启动/打包脚本
│   ├── start.bat                  # Win 开发启动
│   ├── start.command              # Mac 开发启动
│   ├── pack-win.bat               # Win 打包
│   └── pack-mac.command           # Mac 打包
│
├── docs/                          # 开发文档
│   ├── PACK_MAC.md                # Mac 打包指南
│   ├── RAG_GUIDE.md               # RAG 使用指南
│   ├── RELEASE_GUIDE.md           # 发布指南
│   ├── knowledge_base.md          # 知识库（含 AI 分析输出）
│   └── archive/                   # 历史文档归档
│
├── logs/                          # 运行日志（.gitignore）
├── history/                       # 每日岗位快照（.gitignore）
├── release/                       # 打包产物（.gitignore）
│
├── jobs_data.json                 # 岗位数据主文件（看板数据源）
├── AIPM总表_统一格式.csv           # 最新 CSV 快照
├── requirements.txt               # Python 依赖
├── package.json                   # Electron 项目配置
└── README.md
```

---

## 🔧 环境要求

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 爬虫、守护进程 |
| Node.js | 18+ | Electron 应用 |
| Chrome | 最新版 | BOSS 直聘爬虫 |

### 安装依赖
```bash
# Python
pip install -r requirements.txt

# Node
npm install
```

---

## 🛠 构建与打包

```bash
# Windows 打包 NSIS 安装包 + portable
npm run pack:win
# 或双击 launcher/pack-win.bat

# macOS 打包 dmg
npm run pack:mac
# 或双击 launcher/pack-mac.command

# 同时打包 Windows + macOS（仅能在 macOS 跨平台）
npm run pack:all
```

产物位于 `release/` 目录。

---

## ⚙️ 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `AI_PM_UNATTENDED` | 无人值守模式（禁用所有弹窗） | `0` 命令行 / `1` Electron |
| `AI_PM_SHOW_PROGRESS_GUI` | 已废弃（原 Tkinter 弹窗开关，现 UI 统一 Electron） | `0` |
| `AI_PM_OPEN_REPORT` | 爬取结束后自动打开报告 | `1` 命令行 / `0` Electron |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用凭证 | 从 `.env` 读取 |
| `FEISHU_DOC_TOKEN` | 飞书文档 Token | 从 `.env` 读取 |

---

## 🔐 安全与隐私

- **Cookie 安全**：登录态只保存在本地 `.chrome_profile/`（`.gitignore` 内）
- **无后门**：全部代码开源，无任何遥测上报
- **本地优先**：数据完全保存在本机，用户 100% 掌控

---

## 📜 许可证

MIT License — 仅限学习与研究使用。

## 🔗 相关链接

- **GitHub**：<https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard>
- **在线看板**：<https://liyanlong123456dsf.github.io/ai-pm-job-dashboard/>
- **Electron**：<https://www.electronjs.org/>
- **DrissionPage**：<https://github.com/g1879/DrissionPage>
