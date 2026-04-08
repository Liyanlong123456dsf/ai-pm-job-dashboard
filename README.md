# AI 产品经理岗位分析 Dashboard

每日自动爬取 BOSS 直聘最新 AI 产品经理及强相关岗位，可视化分析薪资、城市、方向分布。

## 在线预览

直接用浏览器打开 `job_dashboard.html`（需要本地启动 HTTP 服务）：

```bash
cd 工作集合表
python3 -m http.server 8765
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
pip3 install DrissionPage

# 2. 首次登录（只需一次，Cookie 自动保存）
cd scripts
python3 spiders/boss_dp.py --login

# 3. 手动运行一次测试
python3 spiders/boss_dp.py --quick --merge
```

### 自动抓取命令

```bash
# 快速模式（2关键词×10城市 ≈ 20分钟）
python3 spiders/boss_dp.py --quick --merge

# 全量模式（5关键词×10城市 ≈ 45分钟）
python3 spiders/boss_dp.py --merge
```

### 定时任务（macOS launchd）

```bash
# 自行创建 plist 或用 crontab
crontab -e
# 添加：每天早上 7:00 自动抓取
0 7 * * * cd ~/Desktop/工作集合表/scripts && python3 spiders/boss_dp.py --quick --merge >> ~/Desktop/工作集合表/logs/cron.log 2>&1
```

## 项目结构

```
├── job_dashboard.html       # 可视化 Dashboard（纯前端）
├── jobs_data.json           # 岗位数据（Dashboard 数据源）
├── scripts/
│   ├── spiders/
│   │   └── boss_dp.py       # BOSS直聘爬虫（API拦截+强相关过滤）
│   ├── pipeline.py          # 数据清洗管道
│   ├── merger.py            # 增量合并
│   └── daily_update.py      # 每日更新主入口
├── config/
│   ├── keywords.json        # 关键词与城市配置
│   └── cookies.json         # Cookie 配置（已弃用，改用持久化Profile）
├── PRD_每日岗位自动更新.md  # 产品需求文档
└── README.md
```

## 技术方案

- **爬虫**: DrissionPage 自动化浏览器 + API 拦截（监听 `joblist.json` 接口）
- **防封**: 持久化 Chrome Profile、随机延迟、模拟人类滚动
- **过滤**: 双重关键词匹配（AI词 + 产品词）确保强相关
- **去重**: 基于 职位名+公司名 的 SHA256 哈希去重
- **前端**: 纯 HTML/CSS/JS，Apple 设计风格，无需框架
