/**
 * Renderer: 前端交互逻辑 · 通过 window.api 调用主进程
 */

// ========== Tab 切换 ==========
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    const tab = t.dataset.tab;
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === t));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.dataset.panel === tab));
    if (tab === 'logs') refreshFileLog();
    if (tab === 'config') loadConfig();
    if (tab === 'history') loadHistory();
    if (tab === 'dashboard') reloadDashboard();
  });
});

// ========== Runner 控制 ==========
async function startRunner(action) {
  const r = await api.startRunner(action);
  if (!r.ok) toast(r.error || '启动失败', 'err');
  else toast(`已启动 (PID=${r.pid})`, 'ok');
}

async function stopRunner(action) {
  const r = await api.stopRunner(action);
  if (!r.ok) toast(r.error || '停止失败', 'err');
  else toast('已停止', 'ok');
}

// 状态更新（来自主进程推送）
const LAST_RUNNING = {}; // 记录上次运行状态，用于检测"刚刚完成"
api.onRunnerStatus(status => {
  for (const k of Object.keys(status)) {
    const cell = document.getElementById(`pid-${k}`);
    const card = document.querySelector(`.action-card[data-runner="${k}"]`);
    const wasRunning = !!LAST_RUNNING[k];
    const isRunning = !!status[k].running;
    LAST_RUNNING[k] = isRunning;

    // 刚刚从运行变为未运行 → 刷新对应状态面板
    if (wasRunning && !isRunning) {
      if (k === 'stale_cleanup') refreshCleanupStatus();
      if (k === 'sync_feishu') refreshFeishuStatus();
      if (k === 'auto_daily' || k === 'one_round') {
        refreshCleanupStatus();
        refreshFeishuStatus();
      }
    }

    if (!cell) continue;
    if (isRunning) {
      cell.textContent = `PID ${status[k].pid} · 运行中`;
      cell.classList.add('active');
      if (card) card.classList.add('running');
    } else {
      cell.textContent = '未运行';
      cell.classList.remove('active');
      if (card) card.classList.remove('running');
    }
  }
  // 顶部状态指示
  const anyRunning = Object.values(status).some(v => v.running);
  const runDot = document.querySelector('.status');
  const runLabel = document.getElementById('runLabel');
  if (runDot) runDot.classList.toggle('running', anyRunning);
  if (runLabel) runLabel.textContent = anyRunning ? '运行中' : '待机';
});

// ========== 实时日志 ==========
const LOG_BUF = [];
const LOG_MAX = 3000;
let autoScroll = true;
let currentLogTab = 'live';

api.onRunnerLog(({ runner, stream, text }) => {
  const line = `[${runner}] ${text}`;
  LOG_BUF.push({ runner, stream, text });
  if (LOG_BUF.length > LOG_MAX) LOG_BUF.shift();
  if (currentLogTab === 'live') appendLogLine(line, stream);
});

function appendLogLine(text, stream = 'stdout') {
  const box = document.getElementById('logBox');
  if (!box) return;
  const span = document.createElement('span');
  let cls = '';
  const t = text.toLowerCase();
  if (/error|\❌|fail/i.test(text)) cls = 'err';
  else if (/warn|warning/i.test(text)) cls = 'warn';
  else if (/✅|success|完成/i.test(text)) cls = 'success';
  else if (stream === 'stderr') cls = 'err';
  else cls = 'meta';
  span.className = cls;
  span.textContent = text;
  box.appendChild(span);
  if (autoScroll) box.scrollTop = box.scrollHeight;
}

document.querySelectorAll('.log-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.log-tab').forEach(x => x.classList.toggle('active', x === tab));
    currentLogTab = tab.dataset.log;
    const box = document.getElementById('logBox');
    box.textContent = '';
    if (currentLogTab === 'live') {
      LOG_BUF.slice(-300).forEach(l => appendLogLine(`[${l.runner}] ${l.text}`, l.stream));
    } else {
      api.tailLog(currentLogTab, 500).then(text => {
        box.textContent = text || '（暂无日志）';
        if (autoScroll) box.scrollTop = box.scrollHeight;
      });
    }
  });
});

function clearLog() {
  const box = document.getElementById('logBox');
  if (box) box.textContent = '';
  if (currentLogTab === 'live') LOG_BUF.length = 0;
}

function toggleAutoScroll() {
  autoScroll = !autoScroll;
  const btn = document.getElementById('scrollBtn');
  if (btn) btn.textContent = `📌 自动滚动: ${autoScroll ? '开' : '关'}`;
}

function refreshFileLog() {
  if (currentLogTab !== 'live') {
    const box = document.getElementById('logBox');
    api.tailLog(currentLogTab, 500).then(text => {
      box.textContent = text || '（暂无日志）';
      if (autoScroll) box.scrollTop = box.scrollHeight;
    });
  }
}

// ========== Tick: 进度 + 状态 + 账号池 ==========
const TASK_META = {
  crawl:   { title: '📊 当前爬取进度',  badge: '🔍 爬取', cls: 'badge-crawl' },
  cleanup: { title: '🧹 当前清洗进度',  badge: '🧹 清洗', cls: 'badge-cleanup' },
};

api.onTick(({ progress, status, pool }) => {
  if (progress) {
    const pct = progress.pct || 0;
    document.getElementById('progressFill').style.width = `${pct}%`;
    document.getElementById('progressPct').textContent = `${pct}%`;
    document.getElementById('progressPhase').textContent = progress.phase || '等待…';
    document.getElementById('progressTs').textContent = progress.ts || '';

    // 根据 task_type 动态切换标题和徽章
    const tt = progress.task_type;
    const meta = TASK_META[tt];
    const titleEl = document.getElementById('progressTitle');
    const badgeEl = document.getElementById('taskTypeBadge');
    if (meta && !progress.done) {
      if (titleEl) titleEl.textContent = meta.title;
      if (badgeEl) {
        badgeEl.textContent = meta.badge;
        badgeEl.className = `task-badge ${meta.cls}`;
        badgeEl.style.display = '';
      }
    } else {
      if (titleEl) titleEl.textContent = '📊 当前轮次进度';
      if (badgeEl) badgeEl.style.display = 'none';
    }

    const ul = document.getElementById('stepsList');
    if (ul && progress.steps) {
      ul.innerHTML = progress.steps.slice(-8).map(s => {
        const icon = s.ok === true ? '✓' : s.ok === false ? '✕' : '○';
        const cls = s.ok === true ? 'ok' : s.ok === false ? 'fail' : '';
        return `<li class="step ${cls}">
          <span class="s-icon">${icon}</span>
          <span class="s-name">${esc(s.name || '')}</span>
          <span class="s-detail">${esc(s.detail || '')}</span>
          <span class="s-time">${esc(s.time || '')}</span>
        </li>`;
      }).join('');
    }
  }
  if (status) {
    setText('kpiTotal', status.total ?? '—');
    setText('kpiAdded', status.added ?? '—');
    setText('kpiRaw', status.crawl_raw ?? '—');
    setText('kpiCleaned', status.crawl_cleaned ?? '—');
    setText('kpiErrs', (status.errors || []).length);
  }
  if (pool) renderPool(pool);
});

// ========== BOSS 账号池 ==========
function renderPool(pool) {
  const grid = document.getElementById('poolGrid');
  const meta = document.getElementById('poolMeta');
  const hint = document.getElementById('poolHint');
  if (!grid) return;

  const accounts = pool.accounts || [];
  if (!accounts.length) {
    grid.innerHTML = '<div style="text-align:center;color:var(--text-40);padding:24px">未配置账号（编辑 config/boss_accounts.json）</div>';
    if (meta) meta.textContent = '—';
    if (hint) hint.classList.remove('show');
    return;
  }

  const fmt = s => s ? esc(s) : '—';
  const healthyCount = accounts.filter(a => a.status === 'healthy').length;
  if (meta) {
    meta.textContent = `${healthyCount}/${accounts.length} healthy${pool.current_account ? ` · 当前 ${esc(pool.current_account)}` : ''}`;
  }

  grid.innerHTML = accounts.map(a => {
    const isCurrent = pool.current_account === a.alias;
    const statusText = a.status === 'failed' ? '❌ 失效' : '✅ 正常';
    const lastInfo = a.status === 'failed' && a.last_fail
      ? `失效于 ${esc(a.last_fail)}`
      : (a.last_ok ? `上次成功 ${esc(a.last_ok)}` : '未使用过');
    const detail = a.status === 'failed' && a.last_fail_detail
      ? `<div class="pool-detail">${fmt(a.last_fail_detail)}</div>` : '';
    return `
      <div class="pool-acc ${a.status} ${isCurrent ? 'current' : ''}">
        <div class="pool-head">
          <span class="pool-dot"></span>
          <span class="pool-name">${esc(a.alias)}</span>
          <span style="margin-left:auto;font-size:12px;color:var(--text-60)">${statusText}</span>
        </div>
        <div class="pool-meta">profile: ${esc(a.profile_dir)}</div>
        <div class="pool-meta">${lastInfo} · 成功 ${a.success_count} · 失败 ${a.fail_count}</div>
        ${detail}
        <div class="pool-ctrl">
          <button class="btn btn-primary" onclick='bossManualLogin(${JSON.stringify(a.alias)})'>扫码登录</button>
          ${a.status === 'failed' ? `<button class="btn" onclick='bossResetAccount(${JSON.stringify(a.alias)})'>重置为正常</button>` : ''}
        </div>
      </div>
    `;
  }).join('');

  if (hint) {
    if (pool.all_failed) {
      hint.classList.add('show', 'crit');
      hint.textContent = '🚨 所有账号均已失效！请点击任一账号的「扫码登录」按钮，在 Chrome 中完成登录后，下一轮将自动恢复。';
    } else if (accounts.some(a => a.status === 'failed')) {
      hint.classList.add('show');
      hint.classList.remove('crit');
      hint.textContent = '⚠️ 部分账号失效，守护进程将自动切换到可用账号；若所有账号都失效会通过飞书推送提醒。';
    } else {
      hint.classList.remove('show', 'crit');
    }
  }
}

async function bossManualLogin(alias) {
  const r = await api.bossManualLogin(alias);
  if (!r.ok) toast(r.error || '启动登录失败', 'err');
  else toast(`已启动账号 [${alias}] 登录 (PID=${r.pid})`, 'ok');
}

async function bossResetAccount(alias) {
  const r = await api.bossResetAccount(alias);
  if (!r.ok) toast(r.error || '重置失败', 'err');
  else toast(`账号 [${alias}] 已重置为正常`, 'ok');
}

async function refreshPool() {
  try {
    const pool = await api.bossPoolStatus();
    renderPool(pool);
  } catch (_) {}
}

// ========== 飞书告警 & 岗位日报 ==========
const FEISHU_ALERT_LABELS = {
  manual_test: '手动文本测试',
  boss_pool_all_failed: '账号池全部失效',
  daily_report: '岗位日报',
  generic: '通用',
  account_recovered: '账号恢复',
};

async function refreshFeishuStatus() {
  try {
    const st = await api.feishuStatus();
    const dot = document.getElementById('fsDot');
    const txt = document.getElementById('fsText');
    const meta = document.getElementById('feishuMeta');
    const hist = document.getElementById('feishuHistory');
    if (!dot || !txt) return;

    if (st.configured) {
      dot.className = 'fs-dot ok';
      txt.textContent = `Webhook 已配置${st.has_secret ? ' · 签名校验 ✓' : ''}`;
      if (meta) meta.textContent = '已连接';
    } else if (st.has_webhook) {
      dot.className = 'fs-dot warn';
      txt.textContent = 'Webhook 格式异常（应以 https://open.feishu.cn/open-apis/bot/v2/hook/ 开头）';
      if (meta) meta.textContent = '配置异常';
    } else {
      dot.className = 'fs-dot off';
      txt.textContent = '未配置 Webhook（请在 .env 中设置 FEISHU_ALERT_WEBHOOK）';
      if (meta) meta.textContent = '未配置';
    }

    // 按钮启用/禁用
    const btns = document.querySelectorAll('.feishu-actions .btn');
    btns.forEach(b => { if (b.id !== 'btnFeishuReset') b.disabled = !st.configured; });

    // 发送历史
    if (hist && st.alerts && st.alerts.length > 0) {
      hist.innerHTML = '<div class="fs-hist-title">发送记录</div>' +
        st.alerts.map(a => {
          const label = FEISHU_ALERT_LABELS[a.key] || a.key;
          return `<div class="fs-hist-item"><span class="fs-hist-key">${esc(label)}</span><span class="fs-hist-val">${esc(a.last_sent_at || '—')} · 共 ${a.total_sent} 次</span></div>`;
        }).join('');
    } else if (hist) {
      hist.innerHTML = '<div class="fs-hist-title">暂无发送记录</div>';
    }
  } catch (_) {}
}

async function feishuAction(apiCall, label) {
  const result = document.getElementById('feishuResult');
  if (result) { result.className = 'feishu-result loading'; result.textContent = `正在${label}…`; }
  try {
    const r = await apiCall();
    if (r.ok) {
      toast(`${label}成功，请查看手机飞书`, 'ok');
      if (result) { result.className = 'feishu-result ok'; result.textContent = `✅ ${label}成功`; }
    } else {
      toast(`${label}失败: ${r.error || '未知错误'}`, 'err');
      if (result) { result.className = 'feishu-result err'; result.textContent = `❌ ${r.error || '失败'}`; }
    }
    refreshFeishuStatus();
  } catch (e) {
    toast(`${label}异常: ${e.message || e}`, 'err');
    if (result) { result.className = 'feishu-result err'; result.textContent = `❌ ${e.message || '异常'}`; }
  }
}

// 绑定按钮
document.getElementById('btnFeishuTest')?.addEventListener('click', () => feishuAction(api.feishuTest, '发送测试文本'));
document.getElementById('btnFeishuTestAlert')?.addEventListener('click', () => feishuAction(api.feishuTestAlert, '发送账号失效告警'));
document.getElementById('btnFeishuTestReport')?.addEventListener('click', () => feishuAction(api.feishuTestReport, '推送岗位日报'));
document.getElementById('btnFeishuReset')?.addEventListener('click', () => feishuAction(api.feishuResetThrottle, '清除节流'));

// ========== 数据清洗 ==========
async function refreshCleanupStatus() {
  try {
    const st = await api.cleanupStatus();
    const info = document.getElementById('cleanupInfo');
    const meta = document.getElementById('cleanupMeta');
    const hist = document.getElementById('cleanupHistory');
    if (!info) return;

    if (st.last) {
      const l = st.last;
      info.innerHTML = `<div class="cu-summary">上次清洗: <strong>${esc(l.date)}</strong> · 检查 ${l.checked} 条 · 删除 ${l.removed} 条 · 刷新 ${l.refreshed} 条 · 剩余 ${l.remaining} 条</div><div class="cu-interval">清洗间隔: 每 <strong>${st.interval}</strong> 天</div>`;
      if (meta) meta.textContent = `每${st.interval}天 · 上次 ${l.date}`;
    } else {
      info.innerHTML = `<div class="cu-summary">尚未执行过清洗</div><div class="cu-interval">清洗间隔: 每 <strong>${st.interval}</strong> 天</div>`;
      if (meta) meta.textContent = `每${st.interval}天`;
    }

    if (hist && st.history && st.history.length > 0) {
      hist.innerHTML = '<div class="fs-hist-title">清洗记录</div>' +
        st.history.map(r => `<div class="fs-hist-item"><span class="fs-hist-key">${esc(r.date)}</span><span class="fs-hist-val">检${r.checked} 删${r.removed} 刷${r.refreshed} 余${r.remaining}</span></div>`).join('');
    } else if (hist) {
      hist.innerHTML = '';
    }
  } catch (_) {}
}

// ========== 配置 ==========
let CFG_CACHE = null;
async function loadConfig() {
  const cfg = await api.readConfig();
  if (!cfg) { toast('读取配置失败', 'err'); return; }
  CFG_CACHE = cfg;

  document.getElementById('kwList').value = (cfg.keywords || []).join('\n');
  setText('kwCount', `${(cfg.keywords || []).length} 个`);

  const cities = cfg.cities || {};
  document.getElementById('cityList').value = Object.entries(cities).map(([k, v]) => `${k}=${v}`).join('\n');
  setText('cityCount', `${Object.keys(cities).length} 个`);

  const s = cfg.schedule || {};
  document.getElementById('cfgInterval').value = s.interval_minutes ?? 10;
  document.getElementById('cfgMode').value = s.mode || 'continuous';
  document.getElementById('cfgAlwaysFull').checked = !!s.always_full;

  const ks = cfg.keyword_settings || {};
  document.getElementById('cfgSampleMin').value = ks.sample_min ?? 5;
  document.getElementById('cfgSampleMax').value = ks.sample_max ?? 8;

  const info = await api.sysInfo();
  const box = document.getElementById('sysInfoBox');
  box.innerHTML = [
    ['版本', `v${info.version}`],
    ['平台', `${info.platform} (${info.arch})`],
    ['Python', info.python || '未检测到'],
    ['项目目录', info.repoRoot],
    ['脚本目录', info.scriptsDir],
    ['配置目录', info.configDir],
    ['日志目录', info.logsDir],
  ].map(([k, v]) => {
    const ok = (k === 'Python' && info.python) || k !== 'Python';
    const cls = !info.python && k === 'Python' ? 'err' : 'ok';
    return `<div class="row"><span class="k">${k}</span><span class="v ${ok ? '' : cls}">${esc(String(v))}</span></div>`;
  }).join('');
}

function addSampleKeyword() {
  const samples = ['AI产品经理', 'AIGC产品经理', '大模型产品经理', 'Agent产品经理', '多模态产品经理'];
  const ta = document.getElementById('kwList');
  const cur = ta.value.trim().split('\n').filter(Boolean);
  samples.forEach(s => { if (!cur.includes(s)) cur.push(s); });
  ta.value = cur.join('\n');
  setText('kwCount', `${cur.length} 个`);
}

async function saveKeywords() {
  if (!CFG_CACHE) await loadConfig();
  const list = document.getElementById('kwList').value.trim().split('\n').map(x => x.trim()).filter(Boolean);
  if (list.length < 3) { toast('至少保留 3 个关键词', 'err'); return; }
  CFG_CACHE.keywords = Array.from(new Set(list));
  const ok = await api.writeConfig(CFG_CACHE);
  if (ok) { toast(`已保存 ${CFG_CACHE.keywords.length} 个关键词`, 'ok'); setText('kwCount', `${CFG_CACHE.keywords.length} 个`); }
  else toast('保存失败', 'err');
}

async function saveCities() {
  if (!CFG_CACHE) await loadConfig();
  const lines = document.getElementById('cityList').value.trim().split('\n').map(x => x.trim()).filter(Boolean);
  const cities = {};
  for (const line of lines) {
    const [name, code] = line.split(/[=:\s]+/);
    if (name && code) cities[name.trim()] = code.trim();
  }
  if (Object.keys(cities).length < 1) { toast('至少保留 1 个城市', 'err'); return; }
  CFG_CACHE.cities = cities;
  const ok = await api.writeConfig(CFG_CACHE);
  if (ok) { toast(`已保存 ${Object.keys(cities).length} 个城市`, 'ok'); setText('cityCount', `${Object.keys(cities).length} 个`); }
  else toast('保存失败', 'err');
}

async function saveSchedule() {
  if (!CFG_CACHE) await loadConfig();
  CFG_CACHE.schedule = CFG_CACHE.schedule || {};
  CFG_CACHE.schedule.interval_minutes = parseInt(document.getElementById('cfgInterval').value, 10) || 10;
  CFG_CACHE.schedule.mode = document.getElementById('cfgMode').value;
  CFG_CACHE.schedule.always_full = document.getElementById('cfgAlwaysFull').checked;
  CFG_CACHE.keyword_settings = CFG_CACHE.keyword_settings || {};
  CFG_CACHE.keyword_settings.sample_min = parseInt(document.getElementById('cfgSampleMin').value, 10) || 5;
  CFG_CACHE.keyword_settings.sample_max = parseInt(document.getElementById('cfgSampleMax').value, 10) || 8;

  const ok = await api.writeConfig(CFG_CACHE);
  toast(ok ? '调度配置已保存' : '保存失败', ok ? 'ok' : 'err');
}

// ========== 历史 ==========
async function loadHistory() {
  const records = await api.getRecords();
  const chart = document.getElementById('histChart');
  const body = document.getElementById('histBody');
  if (!records || records.length === 0) {
    chart.innerHTML = '<div style="text-align:center;color:var(--text-40);padding:40px">暂无历史记录</div>';
    body.innerHTML = '';
    setText('hisSummary', '0 条');
    return;
  }
  const recent = records.slice(-30);
  const maxDur = Math.max(...recent.map(r => r.duration_sec || 0), 1);

  chart.innerHTML = recent.map(r => {
    const h = ((r.duration_sec || 0) / maxDur) * 100;
    return `<div class="hist-bar ${r.success ? '' : 'fail'}"
                 style="height:${Math.max(h, 4)}%"
                 data-tip="第${r.round}轮 · ${r.duration_sec}秒 · ${r.success ? '成功' : '失败'}"></div>`;
  }).join('');

  const success = records.filter(r => r.success).length;
  setText('hisSummary', `共 ${records.length} 条 · 成功率 ${(success / records.length * 100).toFixed(0)}%`);

  body.innerHTML = records.slice().reverse().slice(0, 50).map(r => `
    <tr>
      <td>#${r.round}</td>
      <td>${esc(r.executed_at || '')}</td>
      <td>${esc(r.mode || '')}</td>
      <td class="${r.success ? 'ok' : 'fail'}">${r.success ? '✓ 成功' : '✕ 失败'}</td>
      <td>${formatDuration(r.duration_sec)}</td>
      <td>${esc(r.error || '—')}</td>
    </tr>
  `).join('');
}

// ========== Dashboard iframe 热更新 ==========
function reloadDashboard() {
  const f = document.getElementById('dashFrame');
  if (f) f.contentWindow.location.reload();
}

// ========== 工具 ==========
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }
function formatDuration(sec) {
  if (!sec) return '—';
  const m = Math.floor(sec / 60), s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function toast(msg, type = 'ok') {
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  Object.assign(t.style, {
    position: 'fixed', bottom: '24px', right: '24px', zIndex: 9999,
    padding: '12px 20px', borderRadius: '10px',
    background: type === 'err' ? 'rgba(255,55,95,.15)' : 'rgba(48,209,88,.15)',
    color: type === 'err' ? '#ff6680' : '#30d158',
    border: `1px solid ${type === 'err' ? 'rgba(255,55,95,.35)' : 'rgba(48,209,88,.35)'}`,
    fontSize: '13px', fontWeight: '500',
    backdropFilter: 'blur(12px)',
    opacity: '0', transform: 'translateY(8px)',
    transition: 'all .3s cubic-bezier(.22,1,.36,1)',
  });
  document.body.appendChild(t);
  requestAnimationFrame(() => { t.style.opacity = '1'; t.style.transform = 'translateY(0)'; });
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateY(8px)';
    setTimeout(() => t.remove(), 300);
  }, 2600);
}

// ========== 初始化 ==========
(async function init() {
  const info = await api.sysInfo();
  document.getElementById('appVer').textContent = `v${info.version}`;

  // 初始状态刷新
  const status = await api.runnerStatus();
  for (const k of Object.keys(status)) {
    const cell = document.getElementById(`pid-${k}`);
    const card = document.querySelector(`.action-card[data-runner="${k}"]`);
    if (!cell) continue;
    if (status[k].running) {
      cell.textContent = `PID ${status[k].pid} · 运行中`;
      cell.classList.add('active');
      if (card) card.classList.add('running');
    }
  }

  // 初始数据
  const s = await api.getStatus();
  if (s) {
    setText('kpiTotal', s.total ?? '—');
    setText('kpiAdded', s.added ?? '—');
    setText('kpiRaw', s.crawl_raw ?? '—');
    setText('kpiCleaned', s.crawl_cleaned ?? '—');
    setText('kpiErrs', (s.errors || []).length);
  }
  const p = await api.getProgress();
  if (p) {
    document.getElementById('progressFill').style.width = `${p.pct || 0}%`;
    document.getElementById('progressPct').textContent = `${p.pct || 0}%`;
    document.getElementById('progressPhase').textContent = p.phase || '等待…';
  }

  // 初次加载账号池 + 飞书状态 + 清洗状态
  refreshPool();
  refreshFeishuStatus();
  refreshCleanupStatus();
})();
