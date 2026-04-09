# AI PM 岗位全景分析 - 项目上下文

## 项目概述
BOSS直聘 AI产品经理岗位数据采集 + 可视化看板，部署在 Netlify。

## 技术栈
- **前端**: 单文件 `job_dashboard.html`（原生JS + CSS暗色主题，无框架）
- **爬虫**: Python + DrissionPage（浏览器自动化，API拦截模式）
- **AI对话**: Kimi Code API / Coze API（通过 Netlify 代理转发绕 CORS）
- **部署**: Netlify 静态站（`dist/` 目录，含代理 redirect）
- **数据**: `jobs_data.json`（JSON格式，前端直接 fetch）

## 线上地址
- **Netlify**: https://ai-pm-job-dashboard.netlify.app
- **GitHub Pages**: https://liyanlong123456dsf.github.io/ai-pm-job-dashboard/job_dashboard.html
- **GitHub 仓库**: https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard

## 目录结构
```
工作集合表/
├── dist/                          # Netlify 部署目录（仅含前端文件）
│   ├── job_dashboard.html
│   ├── jobs_data.json
│   ├── index.html
│   └── netlify.toml
├── job_dashboard.html             # 主前端页面（源文件）
├── jobs_data.json                 # 岗位数据（1346条）
├── index.html                     # 跳转页
├── netlify.toml                   # Netlify 配置（publish=dist, API代理）
├── config/
│   └── keywords.json              # 关键词 + 10城市 + 分类规则
├── scripts/
│   ├── daily_update.py            # 每日全流程自动化入口
│   ├── pipeline.py                # 数据清洗（薪资解析/城市归一/分类/去重key）
│   ├── merger.py                  # 增量合并（_key去重，保留_key和_date）
│   ├── backfill_csv.py            # 从CSV+XLSX回填BOSS链接
│   ├── backfill_desc.py           # 补全缺失岗位描述
│   ├── export_total.py            # 导出统一格式总表CSV
│   └── spiders/
│       ├── boss_dp.py             # 主爬虫（DrissionPage + API拦截）
│       └── boss.py                # 辅助爬虫（直接API调用）
├── AIPM4月岗位需求收集_数据表.csv  # 外部数据源1（1978行）
├── 五期1组AIPM四月岗位收集.xlsx    # 外部数据源2（1628行）
├── AIPM总表_统一格式.csv           # 合并导出的统一总表
└── history/                       # 每日快照
```

## 数据模型
每条岗位 `jobs_data.json` 中的字段：
```json
{
  "title": "AI产品经理",
  "company": "字节跳动",
  "city": "北京",
  "salary": "25-50K·15薪",
  "avg": 39.1,
  "tier": "30-50K",
  "exp": "3-5年",
  "edu": "本科",
  "cats": ["大模型/LLM", "AI Agent/智能体"],
  "kw": ["大模型", "Agent"],
  "desc": "岗位描述全文...",
  "url": "https://www.zhipin.com/job_detail/xxx.html",
  "_key": "md5(company+title+norm_city)",
  "_date": "2026-04-09",
  "is_new": true
}
```

## 10大方向分类 + 颜色
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

## 爬虫配置
- **10个城市**: 杭州、上海、北京、深圳、厦门、成都、西安、广州、郑州、南京
- **5个关键词**: AI产品经理、AIGC产品经理、大模型产品经理、人工智能产品经理、智能体产品经理
- **过滤逻辑**: 岗位名必须同时包含"AI相关词"和"产品相关词"
- **详情获取**: 通过 securityId 调 detail API 获取完整描述
- **URL构造**: `https://www.zhipin.com/job_detail/{encryptJobId}.html`
- **登录态**: Chrome Profile 持久化在 `.chrome_profile/`

## 去重机制
- `dedup_key = md5(company + title + norm_city(city))`
- `norm_city`: 取城市名第一段（去掉"·区级"后缀），去掉"市""省"
- `_key` 持久化到 JSON，merger 加载时用 _key 判断新旧

## 链接回填
- 从 CSV + XLSX 两个外部表格构建索引
- 匹配优先级：title+company精确 → title+city精确 → title精确 → 归一化模糊匹配
- 当前覆盖率约 73-91%

## 前端页面结构（5大板块）
1. **总览 Hero**: KPI 卡片（岗位数/方向数/城市数/最高薪资）
2. **方向**: 10大方向卡片 + 关键词 Pills 筛选
3. **薪资图谱**: 散点图（X=城市列, Y=月薪, 颜色=方向） + 薪资分段
4. **城市**: 柱状图对比 + 城市 Pills
5. **自由探索**: 方向×城市×薪资×经验 四维筛选
6. **AI助手**: 右下角悬浮对话框（Kimi/Coze API）
7. **岗位详情弹窗**: 完整描述 + 直达链接 + 同城推荐

## 部署规则
- **发布目录**: `dist/`（仅含 html + json + toml）
- **不要自动部署**: 修改代码后不自动 git push 和 netlify deploy，等用户明确说"上传"或"部署"时才执行
- **每次部署前**: 先同步 dist/ 目录再 deploy

## 每日更新流程（daily_update.py）
1. 爬取（boss_dp.py 全量10城市）
2. 清洗（pipeline.py）
3. 合并去重（merger.py）
4. 回填链接（backfill_csv.py）
5. 补全描述（backfill_desc.py）
6. 导出总表（export_total.py）
7. Git 提交推送
8. 同步 dist + Netlify 部署

## 当前数据状态（2026-04-09）
- 总岗位: 1346 条
- 有链接: 1230 条（91%）
- 有描述: 965 条（72%）
- 城市分布: 杭州280 上海262 北京199 深圳140 成都91 厦门93 西安86 广州75 南京65 郑州53
