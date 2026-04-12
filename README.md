# AI 产品经理岗位分析 Dashboard

每日自动爬取 BOSS 直聘最新 AI 产品经理及强相关岗位，可视化分析薪资、城市、方向分布。

> 支持 **Windows** 和 **macOS** 双平台运行。

## 在线预览

直接用浏览器打开 `job_dashboard.html`（需要本地启动 HTTP 服务）：

```bash
python -m http.server 8765
# 浏览器打开 http://localhost:8765/job_dashboard.html
```

## 数据概况

- **887+ 条** AI PM 强相关岗位
- **10 座城市**：杭州、上海、北京、深圳、厦门、成都、西安、广州、郑州、南京
- **5 个关键词**：AI产品经理、AIGC产品经理、大模型产品经理、人工智能产品经理、智能体产品经理

## 每日自动更新

### 首次使用

```bash
# 1. 安装依赖
pip install DrissionPage

# 2. 首次登录（只需一次，Cookie 自动保存）
cd scripts
python spiders/boss_dp.py --login

# 3. 手动运行一次测试
python spiders/boss_dp.py --quick --merge
```

### 自动抓取命令

```bash
# 快速模式（2关键词×10城市 ≈ 20分钟）
python spiders/boss_dp.py --quick --merge

# 全量模式（5关键词×10城市 ≈ 45分钟）
python spiders/boss_dp.py --merge
```

### 每日全流程一键执行

```bash
# 正常模式
python scripts/daily_update.py

# 快速模式
python scripts/daily_update.py --quick

# 仅测试（不写入文件）
python scripts/daily_update.py --quick --dry-run
```

### 定时任务

#### Windows（任务计划程序）

```powershell
# 以管理员权限运行 PowerShell
cd scripts
.\schedule_manager.ps1 install    # 安装（每天 22:00 自动执行）
.\schedule_manager.ps1 status     # 查看状态
.\schedule_manager.ps1 uninstall  # 卸载
.\schedule_manager.ps1 test       # 立即测试
```

#### macOS（launchd）

```bash
bash scripts/schedule_manager.sh install
bash scripts/schedule_manager.sh status
```

## 项目结构

```
├── job_dashboard.html       # 可视化 Dashboard（纯前端）
├── jobs_data.json           # 岗位数据（Dashboard 数据源）
├── scripts/
│   ├── spiders/
│   │   └── boss_dp.py       # BOSS直聘爬虫（API拦截+强相关过滤）
│   ├── platform_utils.py    # 跨平台工具（通知/弹窗/防休眠）
│   ├── pipeline.py          # 数据清洗管道
│   ├── merger.py            # 增量合并
│   ├── daily_update.py      # 每日更新主入口
│   ├── auto_daily.py        # 22:00 一体化自动流程
│   ├── schedule_manager.ps1 # Windows 定时任务管理
│   └── schedule_manager.sh  # macOS 定时任务管理
├── config/
│   ├── keywords.json        # 关键词与城市配置
│   └── cookies.json         # Cookie 配置（已弃用，改用持久化Profile）
├── 点击查看岗位扒取情况.bat # Windows 双击查看状态
├── 点击查看岗位扒取情况.command # macOS 双击查看状态
└── README.md
```

## 技术方案

- **爬虫**: DrissionPage 自动化浏览器 + API 拦截（监听 `joblist.json` 接口）
- **防封**: 持久化 Chrome Profile、随机延迟、模拟人类滚动
- **过滤**: 双重关键词匹配（AI词 + 产品词）确保强相关
- **去重**: 基于 职位名+公司名 的 MD5 哈希去重
- **前端**: 纯 HTML/CSS/JS，Apple 设计风格，无需框架
- **跨平台**: Windows (ctypes/schtasks) + macOS (osascript/launchd) 双平台支持
