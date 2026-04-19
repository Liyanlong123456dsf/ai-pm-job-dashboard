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
api.onRunnerStatus(status => {
  for (const k of Object.keys(status)) {
    const cell = document.getElementById(`pid-${k}`);
    const card = document.querySelector(`.action-card[data-runner="${k}"]`);
    if (!cell) continue;
    if (status[k].running) {
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

// ========== Tick: 进度 + 状态 ==========
api.onTick(({ progress, status }) => {
  if (progress) {
    const pct = progress.pct || 0;
    document.getElementById('progressFill').style.width = `${pct}%`;
    document.getElementById('progressPct').textContent = `${pct}%`;
    document.getElementById('progressPhase').textContent = progress.phase || '等待…';
    document.getElementById('progressTs').textContent = progress.ts || '';

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
});

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
})();
