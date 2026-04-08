# PRD：AI PM 岗位每日自动抓取与更新

> 版本：v1.0 | 日期：2025-04-08 | 作者：Harry
> 依赖：AI 求职分析助手 Dashboard v1.0

---

## 一、需求背景

当前 Dashboard 基于一次性导入的 523 条静态数据。用户希望每天自动抓取各招聘平台新发布的 AI 产品经理岗位，增量合并到数据集中，使 Dashboard 始终展示最新市场行情。

---

## 二、产品目标

| 目标 | 衡量指标 |
|---|---|
| 数据时效性 | 每日 8:00 前完成更新，数据延迟 ≤24h |
| 增量不重复 | 同一岗位不重复入库，去重准确率 ≥99% |
| 零人工干预 | 定时任务自动运行，仅异常时告警 |
| 数据质量 | 新增岗位字段完整率 ≥95%（标题/公司/城市/薪资） |

---

## 三、功能架构

```
┌──────────────────────────────────────────────────────┐
│                    定时调度层                          │
│            macOS launchd / cron (每日 7:00)           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐     │
│  │ BOSS直聘   │  │ 拉勾       │  │ 猎聘       │     │
│  │  爬虫模块  │  │  爬虫模块  │  │  爬虫模块  │     │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘     │
│        └───────────┬───┘               │             │
│                    ▼                   │             │
│  ┌─────────────────────────────────────┘             │
│  │          数据清洗 & 标准化层                       │
│  │  · 字段映射（统一为 Dashboard 格式）               │
│  │  · 薪资解析（复用 parse_salary）                   │
│  │  · 关键词匹配 & 方向分类                          │
│  │  · 去重（公司+职位+城市 哈希）                     │
│  └─────────────────┬─────────────────────            │
│                    ▼                                 │
│  ┌─────────────────────────────────────┐             │
│  │          数据存储层                  │             │
│  │  jobs_data.json（增量追加）          │             │
│  │  history/2025-04-08.json（每日快照） │             │
│  └─────────────────┬───────────────────┘             │
│                    ▼                                 │
│  ┌─────────────────────────────────────┐             │
│  │       Dashboard 注入 & 刷新         │             │
│  │  重新生成 job_dashboard.html        │             │
│  │  更新 System Prompt 统计摘要        │             │
│  └─────────────────────────────────────┘             │
│                                                      │
├──────────────────────────────────────────────────────┤
│                    监控 & 告警                        │
│          运行日志 + 异常通知（邮件/微信）              │
└──────────────────────────────────────────────────────┘
```

---

## 四、数据源规划

### 4.1 目标平台

| 平台 | 优先级 | 抓取方式 | 数据量预估 |
|---|---|---|---|
| **BOSS直聘** | P0 | API / 页面解析 | 30-80条/天 |
| **拉勾** | P1 | 页面解析 | 10-30条/天 |
| **猎聘** | P1 | API / 页面解析 | 10-20条/天 |
| **脉脉** | P2 | 页面解析 | 5-15条/天 |
| **智联招聘** | P2 | API | 10-20条/天 |

### 4.2 搜索关键词矩阵

```
搜索词 = [
  "AI产品经理", "AI PM", "AIGC产品经理", "大模型产品经理",
  "AI电商产品经理", "AI视频产品经理", "AI内容产品经理",
  "AI策略产品经理", "智能产品经理", "算法产品经理"
]

城市 = ["杭州", "上海", "北京", "深圳", "厦门", "成都", "西安", "广州", "郑州", "南京"]
```

### 4.3 抓取字段映射

| Dashboard 字段 | BOSS直聘 | 拉勾 | 猎聘 |
|---|---|---|---|
| `title` | 岗位名称 | positionName | title |
| `company` | 公司名称 | companyFullName | compName |
| `city` | 城市 | city | city |
| `salary` | 薪资区间 | salary | salary |
| `exp` | 经验要求 | workYear | workingExp |
| `edu` | 学历要求 | education | eduLevel |
| `desc` | 岗位描述（前150字） | positionDetail | jobDesc |
| `cats` | 🔧 由关键词匹配生成 | — | — |
| `kw` | 🔧 由关键词匹配生成 | — | — |
| `avg` | 🔧 由 parse_salary 计算 | — | — |
| `tier` | 🔧 由 avg 计算 | — | — |

---

## 五、详细功能需求

### 5.1 P0 - 爬虫引擎

#### 5.1.1 BOSS直聘爬虫（核心）

| 需求项 | 描述 |
|---|---|
| **请求方式** | 使用 requests + 随机 User-Agent + 请求间隔 3-8s |
| **登录态** | Cookie 方式维持登录（手动获取，有效期 ~7天） |
| **反爬处理** | IP 代理池（可选）、请求频率控制、验证码检测后暂停 |
| **数据提取** | 列表页获取基本信息，详情页获取完整 JD |
| **增量判断** | 根据岗位发布时间过滤，只抓最近 24h 新发布的 |

#### 5.1.2 通用爬虫框架

```python
class JobSpider:
    """所有平台爬虫的基类"""
    
    def __init__(self, platform_name):
        self.platform = platform_name
        self.session = requests.Session()
        self.results = []
    
    def search(self, keyword, city) -> list[dict]:
        """搜索岗位列表，返回标准化结果"""
        raise NotImplementedError
    
    def get_detail(self, job_id) -> dict:
        """获取岗位详情"""
        raise NotImplementedError
    
    def normalize(self, raw_data) -> dict:
        """将平台数据标准化为 Dashboard 格式"""
        raise NotImplementedError
```

### 5.2 P0 - 数据处理管道

#### 5.2.1 清洗规则

| 步骤 | 规则 |
|---|---|
| **字段校验** | title、company、city 不能为空 |
| **薪资解析** | 复用现有 `parse_salary()` 函数 |
| **关键词分类** | 复用现有 `kw_video/kw_ecom/kw_media` 匹配 |
| **描述清洗** | 去除平台水印文字、截断至 150 字 |
| **城市标准化** | "北京市朝阳区" → "北京"，"杭州市" → "杭州" |

#### 5.2.2 去重策略

```
去重键 = MD5(公司名称 + 岗位名称 + 城市)

规则：
1. 与现有 jobs_data.json 中的去重键比对
2. 完全匹配 → 跳过
3. 同公司同城市但标题略有差异 → 模糊匹配（编辑距离 ≤3 视为重复）
4. 新增岗位 → 追加到数据集
```

#### 5.2.3 增量合并流程

```
1. 读取现有 jobs_data.json（N 条）
2. 读取今日爬取结果 new_jobs.json（M 条）
3. 去重过滤 → 得到真正的新增 K 条
4. 合并 → jobs_data.json（N+K 条）
5. 按 avg 降序排序
6. 生成每日快照 history/YYYY-MM-DD.json
7. 重新注入 job_dashboard.html
8. 更新 System Prompt 中的统计数据
```

### 5.3 P0 - 定时调度

#### macOS launchd 配置

```xml
<!-- ~/Library/LaunchAgents/com.aipm.jobcrawler.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aipm.jobcrawler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/harry/Desktop/工作集合表/scripts/daily_update.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/harry/Desktop/工作集合表/logs/crawler.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/harry/Desktop/工作集合表/logs/crawler_error.log</string>
</dict>
</plist>
```

### 5.4 P1 - Dashboard 自动刷新

| 需求项 | 描述 |
|---|---|
| **数据热更新** | Dashboard 启动时从 `jobs_data.json` 文件加载，无需重新构建 HTML |
| **更新时间显示** | Hero 区域显示"数据更新于：2025-04-08 07:00" |
| **新增标记** | 24h 内新增的岗位卡片显示 🆕 标签 |
| **趋势指标** | Hero KPI 显示较昨日变化（如 "+12 条"） |

### 5.5 P1 - 监控告警

| 场景 | 告警方式 | 内容 |
|---|---|---|
| 爬虫运行失败 | 微信/邮件 | 平台名 + 错误信息 |
| 新增岗位为 0 | 微信/邮件 | 可能被反爬，需检查 |
| Cookie 过期 | 微信/邮件 | 需要手动更新 Cookie |
| 数据量异常（>500条/天） | 日志告警 | 可能抓到了非目标数据 |

### 5.6 P2 - 历史趋势分析

| 需求项 | 描述 |
|---|---|
| **每日快照** | 保存 `history/YYYY-MM-DD.json`，用于回溯 |
| **趋势图表** | Dashboard 新增"趋势"Tab，展示岗位数量、均薪、热门关键词的日/周变化曲线 |
| **周报生成** | 每周一由 AI 自动生成本周市场变化摘要 |

---

## 六、技术方案

### 6.1 目录结构

```
工作集合表/
├── job_dashboard.html          # 主页面（已有）
├── jobs_data.json              # 主数据文件（外置，不再内嵌 HTML）
├── scripts/
│   ├── daily_update.py         # 每日主入口脚本
│   ├── spiders/
│   │   ├── __init__.py
│   │   ├── base.py             # 爬虫基类
│   │   ├── boss.py             # BOSS直聘爬虫
│   │   ├── lagou.py            # 拉勾爬虫
│   │   └── liepin.py           # 猎聘爬虫
│   ├── pipeline.py             # 清洗/分类/去重管道
│   ├── merger.py               # 增量合并
│   ├── injector.py             # 注入 Dashboard HTML
│   └── notifier.py             # 告警通知
├── config/
│   ├── keywords.json           # 搜索关键词配置
│   ├── cookies.json            # 各平台 Cookie（加密存储）
│   └── proxy.json              # 代理 IP 配置（可选）
├── history/                    # 每日快照
│   ├── 2025-04-08.json
│   └── ...
├── logs/                       # 运行日志
│   ├── crawler.log
│   └── crawler_error.log
└── PRD_每日岗位自动更新.md     # 本文档
```

### 6.2 数据架构变更

**关键改动：数据外置化**

当前：JSON 数据直接内嵌在 HTML 的 `<script type="application/json">` 中

改为：
```
方案 A（推荐）：HTML 通过 fetch 加载外部 jobs_data.json
方案 B：每次更新后重新生成 HTML（当前方式的自动化版本）
```

**方案 A 实现**：
```javascript
// 替换当前的内嵌数据加载
async function loadData() {
  const resp = await fetch('./jobs_data.json');
  const DATA = await resp.json();
  initDashboard(DATA);
}
loadData();
```

优势：更新数据只需替换 JSON 文件，不需要重新生成 HTML。

### 6.3 daily_update.py 主流程

```python
#!/usr/bin/env python3
"""每日自动更新入口"""

def main():
    log("===== 开始每日更新 =====")
    
    # 1. 抓取
    new_jobs = []
    for Spider in [BossSpider, LagouSpider, LiepinSpider]:
        try:
            spider = Spider()
            jobs = spider.run(KEYWORDS, CITIES)
            new_jobs.extend(jobs)
            log(f"{spider.platform}: 抓取 {len(jobs)} 条")
        except Exception as e:
            notify_error(spider.platform, e)
    
    # 2. 清洗 & 分类
    cleaned = pipeline.process(new_jobs)
    log(f"清洗后: {len(cleaned)} 条")
    
    # 3. 增量合并
    existing = load_json("jobs_data.json")
    merged, added = merger.merge(existing, cleaned)
    log(f"新增: {added} 条, 总计: {len(merged)} 条")
    
    # 4. 保存
    save_json("jobs_data.json", merged)
    save_json(f"history/{today()}.json", cleaned)  # 今日快照
    
    # 5. 注入 Dashboard
    injector.update_html(merged)
    injector.update_system_prompt(merged)
    
    # 6. 通知
    if added == 0:
        notify_warning("今日新增岗位为 0，请检查爬虫状态")
    else:
        notify_success(f"更新完成：新增 {added} 条，总计 {len(merged)} 条")
    
    log("===== 更新完成 =====")
```

---

## 七、反爬策略与合规

### 7.1 反爬应对

| 策略 | 实现 |
|---|---|
| **请求频率** | 每次请求间隔 3-8 秒（随机） |
| **User-Agent** | 随机轮换 10+ 真实浏览器 UA |
| **Cookie 管理** | 定期手动更新，加密本地存储 |
| **IP 代理** | P2 阶段引入，初期用本机 IP |
| **验证码** | 检测到验证码后暂停，发告警通知 |
| **请求量控制** | 每平台每日 ≤500 次请求 |

### 7.2 合规声明

| 原则 | 说明 |
|---|---|
| **仅抓取公开数据** | 只采集公开可见的岗位信息 |
| **尊重 robots.txt** | 遵守各平台 robots.txt 规则 |
| **不存储个人信息** | 不采集招聘方联系方式、HR 信息 |
| **仅限个人使用** | 数据不对外发布、不商用 |
| **最小化请求** | 只抓取必要字段，不深度爬取 |

---

## 八、里程碑计划

| 阶段 | 时间 | 内容 | 交付物 |
|---|---|---|---|
| **M1 - 数据外置** | Day 1 | Dashboard 改为 fetch 加载外部 JSON | 改造后的 HTML + jobs_data.json |
| **M2 - BOSS爬虫** | Day 2-3 | 实现 BOSS直聘爬虫 + 清洗管道 | boss.py + pipeline.py |
| **M3 - 自动合并** | Day 3-4 | 去重 + 增量合并 + HTML 注入 | merger.py + injector.py |
| **M4 - 定时任务** | Day 4 | launchd 定时调度 + 日志 | plist + daily_update.py |
| **M5 - 更多平台** | Day 5-7 | 拉勾 + 猎聘爬虫 | lagou.py + liepin.py |
| **M6 - 监控告警** | Day 7 | 异常通知 + Cookie 过期检测 | notifier.py |
| **M7 - 趋势分析** | Day 8-10 | 历史快照 + 趋势图表 + 周报 | 趋势 Tab + 周报生成器 |

---

## 九、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 平台反爬升级 | 高 | 抓取失败 | 多平台冗余；被封一个不影响整体 |
| Cookie 频繁过期 | 中 | 需手动更新 | 告警通知 + 考虑无头浏览器自动登录（P2） |
| 数据格式变更 | 中 | 解析失败 | 解析器加异常捕获，字段缺失时跳过 |
| 法律合规风险 | 低 | — | 仅个人使用、最小化请求、尊重 robots.txt |
| 数据膨胀 | 低 | 文件过大 | 超过 5000 条时归档旧数据 |

---

## 十、验收标准

| # | 验收条件 | 优先级 |
|---|---|---|
| 1 | 每日 7:00 自动运行爬虫脚本，无需手动触发 | P0 |
| 2 | BOSS直聘能抓取到 AI PM 相关岗位 ≥10 条/天 | P0 |
| 3 | 新增岗位自动合并到 jobs_data.json，无重复 | P0 |
| 4 | Dashboard 刷新后能看到今日新增岗位 | P0 |
| 5 | 新增岗位带有 🆕 标记 | P1 |
| 6 | Hero 区域显示数据更新时间和较昨日变化 | P1 |
| 7 | 爬虫失败时收到告警通知 | P1 |
| 8 | 历史快照可回溯过去 30 天数据 | P2 |
| 9 | 趋势 Tab 展示岗位量和薪资的日变化 | P2 |

---

## 附录 A：可选替代方案

### 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|---|---|---|---|
| **A. 自建爬虫（本 PRD）** | 完全可控、免费、可定制 | 需维护反爬、Cookie | ⭐⭐⭐⭐ |
| **B. 招聘平台 API** | 稳定、合规 | 大多不开放/收费/限制大 | ⭐⭐ |
| **C. 第三方数据服务** | 省心 | 费用高、数据覆盖不确定 | ⭐⭐ |
| **D. RPA 自动化** | 模拟真人、反爬少 | 运行慢、资源占用高 | ⭐⭐⭐ |
| **E. RSS + 聚合站** | 轻量 | 数据不全、延迟高 | ⭐ |

### 附录 B：BOSS直聘页面结构参考

```
搜索 URL: https://www.zhipin.com/web/geek/job?query=AI产品经理&city=101210100
列表接口: /wapi/zpgeek/search/joblist.json
详情接口: /wapi/zpgeek/job/detail.json?securityId=xxx

关键字段路径:
- jobList[].jobName        → title
- jobList[].brandName      → company
- jobList[].cityName       → city
- jobList[].salaryDesc     → salary
- jobList[].jobExperience  → exp
- jobList[].jobDegree      → edu
- jobDetail.postDescription → desc
```
