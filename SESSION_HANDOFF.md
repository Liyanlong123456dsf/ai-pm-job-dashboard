# AI PM 岗位 Dashboard — 会话交接文档

> 本文档是清理上下文前的完整项目快照，下次对话直接发送此文档即可恢复全部上下文。

---

## 一、项目概况

| 项目 | 值 |
|---|---|
| 项目名称 | AI PM 岗位全景分析 Dashboard |
| 项目路径 | `/Users/harry/Desktop/工作集合表` |
| GitHub | https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard |
| GitHub Pages | https://liyanlong123456dsf.github.io/ai-pm-job-dashboard/job_dashboard.html |
| 线上地址 | https://ai-pm-job-dashboard.netlify.app |
| 技术栈 | 前端: 原生JS+CSS暗色主题（无框架）/ 爬虫: Python+DrissionPage / AI: Kimi/Coze API / 部署: Netlify |
| 数据更新时间 | 2026-04-09 13:13 |
| 总岗位数 | 1346 条 |
| 有链接 | 1230/1346（91%） |
| 有描述 | 1254/1346（93%） |
| 去重_key | 1346/1346（100%） |

---

## 二、数据分布

### 城市（10城）
| 城市 | 岗位数 | 均薪 |
|---|---|---|
| 杭州 | 280 | 27.5K |
| 上海 | 262 | 32.5K |
| 北京 | 199 | 30.4K |
| 深圳 | 142 | 29.8K |
| 厦门 | 93 | 17.2K |
| 成都 | 91 | 19.6K |
| 西安 | 86 | 16.1K |
| 广州 | 75 | 22.5K |
| 南京 | 65 | 18.9K |
| 郑州 | 53 | 13.8K |

### 方向（11类）
| 方向 | 岗位数 |
|---|---|
| AI+企业服务/SaaS | 595 |
| 大模型/LLM | 422 |
| AI Agent/智能体 | 415 |
| AI+电商/营销 | 394 |
| AIGC/内容创作 | 349 |
| 多模态/具身智能 | 344 |
| AI+行业应用 | 235 |
| AI+视频/直播 | 214 |
| 智能客服/对话 | 187 |
| AI通用 | 178 |
| AI+新媒体 | 86 |

### 薪资档位
| 档位 | 岗位数 |
|---|---|
| 15-30K | 562 |
| 30-50K | 296 |
| 8-15K | 252 |
| 50K+ | 121 |
| <8K | 115 |

---

## 三、项目文件结构

```
工作集合表/
├── job_dashboard.html          # 前端单页面（Apple风格暗色主题）
├── jobs_data.json              # 核心数据文件（1346条）
├── index.html                  # 重定向到 job_dashboard.html
├── netlify.toml                # Netlify 部署配置
├── config/
│   ├── keywords.json           # 搜索关键词 + 城市ID + 方向分类规则
│   └── cookies.json            # BOSS直聘登录Cookie
├── scripts/
│   ├── daily_update.py         # ★ 每日全流程一键脚本（10步）
│   ├── pipeline.py             # 数据清洗 + 分类打标 + 薪资解析
│   ├── merger.py               # 增量合并 + _key去重
│   ├── backfill_csv.py         # 从CSV/XLSX回填岗位链接
│   ├── backfill_desc.py        # 追踪原链接补全缺失描述
│   ├── backfill_fuzzy.py       # 模糊匹配回填（辅助）
│   ├── backfill_urls.py        # BOSS API回填链接（辅助）
│   ├── export_total.py         # 导出统一格式CSV总表
│   ├── gen_knowledge.py        # 生成知识库MD + 提示词 + RAG文档
│   └── spiders/
│       ├── boss_dp.py          # ★ 主爬虫（DrissionPage自动化）
│       ├── boss.py             # API爬虫（备用）
│       └── __init__.py
├── AIPM4月岗位需求收集_数据表.csv    # 外部数据表1
├── 五期1组AIPM四月岗位收集.xlsx      # 外部数据表2
├── AIPM总表_统一格式.csv             # 导出的统一总表（3791条）
├── history/                          # 每日快照
└── logs/                             # 爬虫日志
```

---

## 四、技术细节

### 爬虫配置
- **10城市**: 杭州、上海、北京、深圳、厦门、成都、西安、广州、郑州、南京
- **5关键词**: AI产品经理、AIGC产品经理、大模型产品经理、人工智能产品经理、智能体产品经理
- **过滤**: 岗位名必须同时包含"AI相关词"和"产品相关词"
- **详情**: 通过 securityId 调 detail API 获取完整描述
- **URL构造**: `https://www.zhipin.com/job_detail/{encryptJobId}.html`
- **登录态**: Chrome Profile 持久化 `.chrome_profile/`

### 去重机制
- `dedup_key = md5(company + title + norm_city(city))`
- `norm_city`: 取第一段（去"·区级"后缀），去"市""省"
- `_key` 持久化到JSON，merger加载时判断新旧

### 链接回填
- 从CSV+XLSX两表构建索引
- 优先级: title+company精确 → title+city → title → 归一化模糊
- 覆盖率: 91%（1230/1346）

### 方向颜色映射（CAT_COLORS）
| 方向 | 颜色 |
|---|---|
| 大模型/LLM | #2997ff |
| AI Agent/智能体 | #5e5ce6 |
| AIGC/内容创作 | #ff9f0a |
| 多模态/具身智能 | #ff375f |
| AI+电商/营销 | #30d158 |
| AI+视频/直播 | #64d2ff |
| 智能客服/对话 | #ffd60a |
| AI+企业服务/SaaS | #bf5af2 |
| AI+行业应用 | #ac8e68 |
| AI+新媒体 | #ff6482 |
| AI通用（默认） | #98989d |

### 部署规则
- **发布目录**: `dist/`（仅含 html+json+toml）
- 修改后先同步 `dist/` 再 deploy
- AI对话通过 Netlify redirect 代理转发绕 CORS

---

## 五、核心流程

### daily_update.py 全流程（一键执行）

```
1. 爬取 → boss_dp.py 抓取10城×5关键词
2. 清洗 → pipeline.py 标准化+分类打标+薪资解析
3. 合并 → merger.py _key去重合并到 jobs_data.json
4. 保存 → 写入JSON + 每日快照到 history/
5. 回填链接 → backfill_csv.py 从CSV/XLSX匹配URL
6. 补全描述 → backfill_desc.py 追踪原链接抓取详情
7. 导出总表 → export_total.py 输出统一CSV
8. Git提交 → 自动 commit + push
9. Netlify部署 → 自动 deploy --prod
10. 汇报 → 输出统计摘要
```

### 数据字段结构（jobs_data.json）

```json
{
  "meta": {"updated": "2026-04-09 13:13", "total": 1346},
  "jobs": [{
    "title": "AI产品经理",
    "company": "字节跳动",
    "city": "北京",
    "salary": "300-500K",
    "avg": 33.3,
    "tier": "30-50K",
    "exp": "3-5年",
    "edu": "本科",
    "cats": ["大模型/LLM", "AI Agent/智能体"],
    "kw": ["NLP", "推荐算法"],
    "desc": "岗位职责...任职要求...",
    "url": "https://www.zhipin.com/job_detail/xxx.html",
    "_key": "md5hash",
    "_date": "2026-04-09"
  }]
}
```

---

## 六、前端架构（job_dashboard.html）

单文件HTML，5个模块：

| 模块 | 功能 | 动态数据来源 |
|---|---|---|
| Hero（总览） | KPI数字 + 更新时间 | 动态统计DATA |
| 十大方向 | 方向卡片 + 关键词pills + 岗位卡片 | `j.cats` 动态分类 |
| 薪资图谱 | 散点图（城市×月薪×方向颜色）+ 薪资pills | `CAT_COLORS` 11色映射 |
| 城市对比 | 柱状图 + 均薪 + 城市pills | `cityMap` 动态统计 |
| 自由探索 | 4维筛选（方向×城市×薪资×经验）+ 结果汇总 | 全部动态从DATA生成 |

**关键设计：**
- 数据通过 `fetch('./jobs_data.json?t=Date.now())` 动态加载
- 散点图颜色由 `CAT_COLORS` 对象映射11大方向
- 所有pills/卡片/图表从数据动态生成，无硬编码
- 岗位详情弹窗含：标签、描述、原始链接、同城推荐

---

## 七、已解决的关键问题

| 问题 | 解决方案 |
|---|---|
| 岗位无直达链接 | 从CSV/XLSX回填 + 爬虫自带encryptJobId构建URL |
| merger保存时丢失_key导致重复入库 | save()保留`_key`和`_date`字段 |
| 散点图颜色只有3分类 | 改为11大方向动态颜色映射 `CAT_COLORS` |
| 散点图X轴不对齐城市 | 改为列宽计算 `colW=W/cities.length` + 列内随机偏移 |
| 自由探索方向/城市不全 | 改为从数据动态生成，不硬编码 |
| 城市对比均薪标签截断 | `bar-info` 加 `flex-shrink:0` + `white-space:nowrap` |
| 309条岗位描述缺失 | `backfill_desc.py` 追踪原链接补全217条 |
| 每日更新需手动多步操作 | `daily_update.py` 10步全流程自动化 |

---

## 八、RAG/Agent 资料（已移出项目）

路径：`/Users/harry/Desktop/AI求职助手_RAG资料/`

| 文件 | 用途 |
|---|---|
| `knowledge_base.md` | 1346条岗位，上传到扣子知识库 |
| `coze_prompt.txt` | Agent系统提示词，粘贴到扣子Bot人设 |
| `RAG_GUIDE.md` | RAG工程搭建指南（策略+步骤+提示词逻辑） |
| `SESSION_HANDOFF.md` | 本文档 |

### 扣子搭建要点速查
1. 知识库上传 `knowledge_base.md`，按`###`自动分段
2. Bot人设粘贴 `coze_prompt.txt`
3. 检索模式：混合检索，Top-K=5-8，阈值0.5
4. 更新时重新运行 `python3 scripts/gen_knowledge.py`

---

## 九、待办/可改进

- [ ] 剩余92条无描述岗位（77条无链接无法追踪）
- [ ] 116条无链接岗位（公司名脱敏无法匹配）
- [ ] 可考虑接入更多招聘平台（拉勾、猎聘）
- [ ] 可加 GitHub Actions 定时执行 daily_update.py
- [ ] 前端可加搜索框全文检索功能
- [ ] 散点图可加交互缩放

---

> **使用方式**：新会话时直接发送本文档，说"请基于这个文档继续工作"即可恢复全部上下文。
