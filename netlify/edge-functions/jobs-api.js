/**
 * Netlify Edge Function — 岗位数据 API
 * 
 * 供扣子(Coze) Bot 通过 API 插件调用，支持多维筛选查询
 * 
 * GET /api/jobs?city=杭州&cat=大模型&exp=3-5年&salary_min=20&keyword=Agent&limit=10
 * 
 * 参数（均可选）:
 *   city       — 城市筛选（模糊匹配）
 *   cat        — 方向分类筛选（模糊匹配，匹配 cats 数组中任一项）
 *   exp        — 经验要求（精确匹配）
 *   edu        — 学历要求（精确匹配）
 *   tier       — 薪资档位（精确匹配，如 "30-50K"）
 *   salary_min — 最低月薪（数字，单位K）
 *   salary_max — 最高月薪（数字，单位K）
 *   keyword    — 关键词搜索（匹配标题/公司/详情/关键词标签）
 *   company    — 公司名筛选（模糊匹配）
 *   limit      — 返回条数上限（默认20，最大50）
 *   offset     — 分页偏移（默认0）
 * 
 * GET /api/jobs/stats — 返回数据概况统计
 */

const SITE_URL = 'https://ai-pm-job-dashboard.netlify.app';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': '*',
  'Content-Type': 'application/json; charset=utf-8',
};

// 缓存数据避免每次请求都 fetch
let cachedData = null;
let cacheTime = 0;
const CACHE_TTL = 5 * 60 * 1000; // 5分钟缓存

async function loadData() {
  const now = Date.now();
  if (cachedData && (now - cacheTime) < CACHE_TTL) {
    return cachedData;
  }
  const resp = await fetch(`${SITE_URL}/jobs_data.json?t=${now}`);
  cachedData = await resp.json();
  cacheTime = now;
  return cachedData;
}

function normCity(c) {
  return (c || '').replace(/[·\s].*/g, '').replace(/[市省]$/, '');
}

export default async (request, context) => {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const url = new URL(request.url);
  const path = url.pathname;

  try {
    const data = await loadData();
    const jobs = data.jobs || [];
    const meta = data.meta || {};

    // === /api/jobs/stats — 数据概况 ===
    if (path === '/api/jobs/stats') {
      const cityMap = {};
      const catMap = {};
      const tierMap = {};
      const expMap = {};
      for (const j of jobs) {
        const c = normCity(j.city);
        cityMap[c] = (cityMap[c] || 0) + 1;
        for (const cat of (j.cats || [])) {
          catMap[cat] = (catMap[cat] || 0) + 1;
        }
        if (j.tier) tierMap[j.tier] = (tierMap[j.tier] || 0) + 1;
        if (j.exp) expMap[j.exp] = (expMap[j.exp] || 0) + 1;
      }
      return new Response(JSON.stringify({
        updated: meta.updated,
        total: jobs.length,
        cities: cityMap,
        categories: catMap,
        salary_tiers: tierMap,
        experience: expMap,
      }, null, 2), { headers: corsHeaders });
    }

    // === /api/jobs — 查询岗位 ===
    const params = url.searchParams;
    const city = params.get('city');
    const cat = params.get('cat');
    const exp = params.get('exp');
    const edu = params.get('edu');
    const tier = params.get('tier');
    const salaryMin = params.get('salary_min') ? parseFloat(params.get('salary_min')) : null;
    const salaryMax = params.get('salary_max') ? parseFloat(params.get('salary_max')) : null;
    const keyword = params.get('keyword');
    const company = params.get('company');
    const limit = Math.min(parseInt(params.get('limit') || '20'), 50);
    const offset = parseInt(params.get('offset') || '0');

    let filtered = jobs;

    if (city) {
      const nc = normCity(city);
      filtered = filtered.filter(j => normCity(j.city).includes(nc));
    }
    if (cat) {
      filtered = filtered.filter(j =>
        (j.cats || []).some(c => c.includes(cat))
      );
    }
    if (exp) {
      filtered = filtered.filter(j => j.exp === exp);
    }
    if (edu) {
      filtered = filtered.filter(j => j.edu === edu);
    }
    if (tier) {
      filtered = filtered.filter(j => j.tier === tier);
    }
    if (salaryMin !== null) {
      filtered = filtered.filter(j => (j.avg || 0) >= salaryMin);
    }
    if (salaryMax !== null) {
      filtered = filtered.filter(j => (j.avg || 0) <= salaryMax);
    }
    if (company) {
      filtered = filtered.filter(j =>
        (j.company || '').includes(company)
      );
    }
    if (keyword) {
      const kw = keyword.toLowerCase();
      filtered = filtered.filter(j =>
        (j.title || '').toLowerCase().includes(kw) ||
        (j.company || '').toLowerCase().includes(kw) ||
        (j.desc || '').toLowerCase().includes(kw) ||
        (j.kw || []).some(k => k.toLowerCase().includes(kw))
      );
    }

    // 按月薪降序排列
    filtered.sort((a, b) => (b.avg || 0) - (a.avg || 0));

    const total = filtered.length;
    const paged = filtered.slice(offset, offset + limit);

    // 返回精简字段（减少token消耗）
    const results = paged.map(j => ({
      title: j.title,
      company: j.company,
      city: normCity(j.city),
      salary: j.salary,
      avg_monthly: j.avg,
      tier: j.tier,
      exp: j.exp,
      edu: j.edu,
      categories: j.cats,
      keywords: j.kw,
      description: (j.desc || '').slice(0, 300),
      url: j.url || null,
    }));

    return new Response(JSON.stringify({
      total_matched: total,
      returned: results.length,
      offset,
      limit,
      data_updated: meta.updated,
      results,
    }, null, 2), { headers: corsHeaders });

  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: corsHeaders,
    });
  }
};
