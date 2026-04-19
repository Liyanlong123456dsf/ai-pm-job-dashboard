# AI PM Job Dashboard

> AI 产品经理岗位一体化桌面应用 · 爬取 · 清洗 · 分析 · 可视化
>
> **Windows + macOS 双平台** · 基于 Electron + Python

![platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![electron](https://img.shields.io/badge/electron-33-9feaf9)
![python](https://img.shields.io/badge/python-3.10%2B-yellow)

---

## ✨ 功能特性

### 🖥 桌面应用（本仓库核心）
- **一体化界面** — 控制台、数据看板、日志、配置、历史记录集成在同一个桌面 app 中
- **一键操作** — 启停守护进程、单轮爬取、登录检查、飞书同步均可点击按钮完成
- **实时监控** — 子进程 stdout 实时流式展示，进度条、KPI 指标、步骤列表全部实时更新
- **可视化配置** — 关键词库、城市列表、调度间隔、采样数量均可在 UI 中编辑

### 🕷 爬虫引擎
- **BOSS 直聘** — 基于 DrissionPage 的 API 拦截（监听 `joblist.json`）
- **50 关键词库** — 每月自动扩展，每轮随机抽取 5-8 个关键词爬取
- **10 热门城市** — 杭州、上海、北京、深圳、厦门、成都、西安、广州、郑州、南京
- **强反封** — 持久化 Chrome Profile、随机延迟、模拟人类滚动
- **智能去重** — 基于「职位名+公司名」MD5 哈希
- **自动清洗** — 失效链接检测、过期岗位清理、薪资/经验/学历结构化
- **失败恢复** — 超时重试、僵尸进程检测、热重载配置

### 📊 数据看板
- **Apple 风格 UI** — 深色主题，动态 Hero 图表，十大方向卡片
- **多维筛选** — 方向 × 城市 × 薪资 × 经验，4 维自由组合
- **薪资图谱** — 气泡散点图（城市 vs 月薪 vs 方向）
- **城市对比** — 柱状图展示各城市岗位密度
- **运行状态** — 每日执行状态、步骤、失败原因一览

### 🚀 自动化
- **全天候循环** — 每 10 分钟重复一轮，崩溃自动重启
- **Git 自动推送** — 每轮完成后自动推送到 GitHub（含代理自动检测）
- **飞书同步** — 知识库自动同步到飞书云文档
- **云部署** — 通过 GitHub Raw URL 自动更新（无需 Netlify）

---

## 🎯 快速开始

### 方案 A：直接运行预打包版本（推荐给普通用户）

从 [Releases](https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard/releases) 下载对应平台的安装包：

| 平台 | 下载 |
|------|------|
| Windows | `AI PM Job Dashboard-1.0.0-Windows-x64.exe` |
| macOS (Apple Silicon) | `AI PM Job Dashboard-1.0.0-macOS-arm64.dmg` |
| macOS (Intel) | `AI PM Job Dashboard-1.0.0-macOS-x64.dmg` |

**注意**：打包版仍需本机安装 Python 3.10+ 才能使用爬取功能（数据看板部分无需 Python）。

### 方案 B：从源码运行（开发者）

**环境要求**
- Node.js 18+ ([下载](https://nodejs.org))
- Python 3.10+ ([下载](https://python.org))
- Chrome 浏览器

**一键启动**

Windows：
```powershell
# 双击
launcher\start.bat
```

macOS：
```bash
# 双击 或终端
chmod +x launcher/start.command
./launcher/start.command
```

首次启动会自动安装 Node.js 和 Python 依赖。

---

## 📦 项目结构

```
ai-pm-job-dashboard/
├── electron/               # Electron 主进程
│   ├── main.js             # 窗口管理 + Python 子进程控制
│   ├── preload.js          # 渲染进程安全桥
│   └── assets/             # 图标资源
├── app/                    # 渲染进程（前端 UI）
│   ├── index.html          # 控制面板主界面
│   ├── dashboard.html      # 数据看板（iframe 嵌入）
│   ├── styles/main.css     # 全局样式
│   └── js/renderer.js      # 前端交互逻辑
├── scripts/                # Python 后端
│   ├── auto_daily.py       # 全天候守护进程
│   ├── daily_update.py     # 单轮主流程
│   ├── login_check.py      # 登录状态检查
│   ├── sync_feishu.py      # 飞书同步
│   ├── gen_knowledge.py    # 知识库生成
│   ├── platform_utils.py   # 跨平台工具
│   └── spiders/
│       └── boss_dp.py      # BOSS 直聘爬虫
├── config/
│   ├── keywords.json       # 关键词 + 城市 + 调度配置
│   └── cookies.json        # Cookie（持久化于 .chrome_profile）
├── launcher/               # 一键脚本
│   ├── start.bat           # Win 开发启动
│   ├── start.command       # Mac 开发启动
│   ├── pack-win.bat        # Win 打包
│   └── pack-mac.command    # Mac 打包
├── logs/                   # 运行日志（.gitignore）
├── jobs_data.json          # 岗位数据（看板数据源）
├── requirements.txt        # Python 依赖
├── package.json            # Electron 项目配置
└── README.md
```

---

## 🎨 桌面应用界面

### 控制台
- 4 张动作卡片：**守护进程 · 单轮爬取 · 登录检查 · 飞书同步**
- 实时进度条 + 步骤列表
- 5 个 KPI 指标：总数 · 新增 · 原始 · 清洗 · 错误

### 数据看板
- 嵌入原 `job_dashboard.html`，体验一致
- 自动检测 Electron 环境，从本地 `jobs_data.json` 读取数据

### 日志
- 3 个 Tab：实时日志 · `auto_daily.log` · `crawler.log`
- 高亮错误（红）/ 警告（橙）/ 成功（绿）
- 可切换自动滚动

### 配置
- **关键词库** — textarea 直接编辑
- **城市列表** — `城市名=编码` 格式
- **调度参数** — 冷却间隔、调度模式、每轮采样数

### 历史记录
- 柱状图展示最近 30 轮耗时
- 详表显示每轮时间、模式、结果、错误信息

---

## 🛠 构建与打包

```bash
# 开发模式（实时重载）
npm run dev

# 打包 Windows（生成 .exe 安装包 + portable）
npm run pack:win
# 或双击 launcher/pack-win.bat

# 打包 macOS（生成 .dmg）
npm run pack:mac
# 或双击 launcher/pack-mac.command

# 同时打包 Win + Mac（仅在 macOS 可跨平台打包）
npm run pack:all
```

打包产物位于 `release/` 目录。

---

## ⚙️ 高级配置

### 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `AI_PM_UNATTENDED` | 无人值守模式（禁用所有弹窗） | `1`（Electron 中） |
| `AI_PM_SHOW_PROGRESS_GUI` | 显示 Tkinter 进度窗口 | `0`（Electron 中） |
| `AI_PM_OPEN_REPORT` | 自动打开报告 | `0` |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书同步凭证 | 从 `.env` 读取 |

### 飞书同步

1. 创建飞书自建应用：https://open.feishu.cn/app
2. 在 `.env` 中配置：
   ```
   FEISHU_APP_ID=cli_xxx
   FEISHU_APP_SECRET=xxx
   FEISHU_DOC_TOKEN=LLdKdmG8FoR6ZXxR58icdTMdnod
   ```
3. 在控制台点击「飞书同步」

### Git 自动推送

代码中会自动检测 `127.0.0.1:7897/7890/1080` 等常见代理端口（适用于 GFW 环境）。

---

## 🔐 安全与隐私

- **Cookie 安全**：登录态存储在 `.chrome_profile/`（已加入 `.gitignore`，不会上传）
- **无后门**：所有代码开源，无任何远程遥测或数据上报
- **本地优先**：爬取的数据全部保存在本地，用户完全掌控

---

## 📜 许可证

MIT License — 仅限学习与研究使用，请勿用于商业侵权。

## 🤝 贡献

欢迎 Issues 和 Pull Requests：https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard

## 🙏 致谢

- [Electron](https://www.electronjs.org/)
- [DrissionPage](https://github.com/g1879/DrissionPage)
- [Apple Design](https://developer.apple.com/design/)
