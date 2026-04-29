/**
 * AI PM Job Dashboard - Electron Main Process
 * 负责: 创建窗口, 管理 Python 子进程, IPC 桥接
 */
const { app, BrowserWindow, ipcMain, shell, Menu, dialog, Tray, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');
const os = require('os');

// ------- 路径基准 -------
const IS_DEV = process.argv.includes('--dev') || !app.isPackaged;
// 开发环境: repo 根目录。打包后: resources 目录（包含 scripts、config）
const APP_ROOT = IS_DEV ? path.join(__dirname, '..') : process.resourcesPath;
const REPO_ROOT = IS_DEV ? path.join(__dirname, '..') : path.join(app.getPath('userData'), 'workspace');
const SCRIPTS_DIR = IS_DEV
  ? path.join(__dirname, '..', 'scripts')
  : path.join(process.resourcesPath, 'scripts');
const CONFIG_DIR = IS_DEV
  ? path.join(__dirname, '..', 'config')
  : path.join(process.resourcesPath, 'config');
const LOGS_DIR = path.join(REPO_ROOT, 'logs');
const DATA_FILE = path.join(REPO_ROOT, 'jobs_data.json');
const STATUS_FILE = path.join(REPO_ROOT, 'run_status.json');
const PROGRESS_FILE = path.join(LOGS_DIR, 'progress.json');
const RECORD_FILE = path.join(LOGS_DIR, 'auto_daily_record.json');
// 账号池相关
const USER_BOSS_ACCOUNTS_FILE = path.join(REPO_ROOT, 'config', 'boss_accounts.json');
const PACKAGED_BOSS_ACCOUNTS_FILE = path.join(CONFIG_DIR, 'boss_accounts.json');
const ACCOUNT_POOL_STATE_FILE = path.join(LOGS_DIR, 'account_pool_state.json');

// 确保运行目录存在
[REPO_ROOT, LOGS_DIR].forEach(p => { if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true }); });

// 打包后首次启动: 复制初始 jobs_data.json / config 到 userData
if (!IS_DEV) {
  const initJobs = path.join(process.resourcesPath, 'jobs_data.json');
  if (fs.existsSync(initJobs) && !fs.existsSync(DATA_FILE)) {
    fs.copyFileSync(initJobs, DATA_FILE);
  }
  const userConfig = path.join(REPO_ROOT, 'config');
  if (!fs.existsSync(userConfig)) {
    fs.mkdirSync(userConfig, { recursive: true });
  }
  ['keywords.json', 'boss_accounts.json'].forEach(f => {
    const src = path.join(process.resourcesPath, 'config', f);
    const dst = path.join(userConfig, f);
    if (fs.existsSync(src) && !fs.existsSync(dst)) fs.copyFileSync(src, dst);
  });
}

// ------- Python 解释器检测 -------
function detectPython() {
  const candidates = process.platform === 'win32'
    ? [
        process.env.PYTHON,
        'C:\\Users\\lenovo\\AppData\\Local\\Programs\\Python\\Python312\\python.exe',
        'C:\\Python312\\python.exe',
        'C:\\Python311\\python.exe',
        'python',
        'py',
      ]
    : [
        process.env.PYTHON,
        '/opt/homebrew/bin/python3',
        '/usr/local/bin/python3',
        '/usr/bin/python3',
        'python3',
      ];
  for (const cmd of candidates) {
    if (!cmd) continue;
    try {
      const out = execSync(`"${cmd}" --version`, { stdio: ['ignore', 'pipe', 'pipe'], timeout: 3000 });
      const ver = out.toString().trim();
      if (/Python 3\.\d+/i.test(ver)) {
        console.log(`[python] detected: ${cmd} (${ver})`);
        return cmd;
      }
    } catch (_) { /* continue */ }
  }
  return null;
}

const PY_EXE = detectPython();

// ------- 子进程管理 -------
const runners = {
  auto_daily: null,   // 全天候守护
  one_round: null,    // 单轮爬取
  login_check: null,  // 登录检查
  sync_feishu: null,  // 飞书同步
  stale_cleanup: null, // 数据清洗
  parallel_crawl: null, // 双浏览器并行
};

function spawnPy(key, scriptRel, args = [], extraEnv = {}) {
  if (!PY_EXE) {
    return { ok: false, error: '未检测到 Python 3，请先安装 Python 3.10+ 并确保在 PATH 中' };
  }
  if (runners[key] && runners[key].pid && !runners[key].killed) {
    return { ok: false, error: `${key} 已在运行 (PID=${runners[key].pid})` };
  }
  const script = path.join(SCRIPTS_DIR, scriptRel);
  if (!fs.existsSync(script)) {
    return { ok: false, error: `脚本不存在: ${script}` };
  }
  const env = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    AI_PM_UNATTENDED: '1',
    AI_PM_SHOW_PROGRESS_GUI: '0',
    AI_PM_OPEN_REPORT: '0',
    AI_PM_BASE_DIR: REPO_ROOT,   // 关键：告诉 Python 脚本用户数据位置
    ...extraEnv,
  };
  const proc = spawn(PY_EXE, ['-u', script, ...args], {
    cwd: REPO_ROOT,
    env,
    windowsHide: true,
  });
  runners[key] = proc;
  broadcast('runner:status', getRunnerStatus());

  proc.stdout.on('data', chunk => {
    const s = chunk.toString('utf-8');
    broadcast('runner:log', { runner: key, stream: 'stdout', text: s });
  });
  proc.stderr.on('data', chunk => {
    const s = chunk.toString('utf-8');
    broadcast('runner:log', { runner: key, stream: 'stderr', text: s });
  });
  proc.on('exit', (code) => {
    broadcast('runner:log', { runner: key, stream: 'info', text: `\n[退出] code=${code}\n` });
    runners[key] = null;
    broadcast('runner:status', getRunnerStatus());
  });
  return { ok: true, pid: proc.pid };
}

function killRunner(key) {
  const proc = runners[key];
  if (!proc) return { ok: false, error: `${key} 未运行` };
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /F /T /PID ${proc.pid}`, { stdio: 'ignore' });
    } else {
      proc.kill('SIGTERM');
      setTimeout(() => { try { proc.kill('SIGKILL'); } catch (_) {} }, 3000);
    }
  } catch (_) {}
  runners[key] = null;
  broadcast('runner:status', getRunnerStatus());
  return { ok: true };
}

function getRunnerStatus() {
  const res = {};
  for (const k of Object.keys(runners)) {
    const p = runners[k];
    res[k] = p && !p.killed ? { running: true, pid: p.pid } : { running: false };
  }
  return res;
}

// ------- 安全读取 JSON -------
function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf-8')); } catch { return null; }
}
function writeJson(file, obj) {
  try {
    const dir = path.dirname(file);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(file, JSON.stringify(obj, null, 2), 'utf-8');
    return true;
  } catch (e) {
    console.error('writeJson', file, e);
    return false;
  }
}

function tailFile(file, lines = 200) {
  if (!fs.existsSync(file)) return '';
  try {
    const data = fs.readFileSync(file, 'utf-8');
    const arr = data.split(/\r?\n/);
    return arr.slice(-lines).join('\n');
  } catch { return ''; }
}

// ------- 窗口 -------
let mainWindow = null;
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: '#000000',
    title: 'AI PM Job Dashboard',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'app', 'index.html'));
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: 'detach' });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function broadcast(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

// ------- IPC 注册 -------
ipcMain.handle('sys:info', () => ({
  python: PY_EXE,
  platform: process.platform,
  arch: process.arch,
  repoRoot: REPO_ROOT,
  scriptsDir: SCRIPTS_DIR,
  configDir: CONFIG_DIR,
  logsDir: LOGS_DIR,
  isDev: IS_DEV,
  version: app.getVersion(),
}));

ipcMain.handle('data:jobs', () => {
  const data = readJson(DATA_FILE) || [];
  return data;
});
ipcMain.handle('data:status', () => readJson(STATUS_FILE));
ipcMain.handle('data:progress', () => readJson(PROGRESS_FILE));
ipcMain.handle('data:records', () => readJson(RECORD_FILE) || []);

// 配置读写都走用户工作区（打包后 userData/workspace/config，开发时仓库 config）
const USER_CONFIG_FILE = path.join(REPO_ROOT, 'config', 'keywords.json');
ipcMain.handle('config:read', () => {
  // 若用户工作区尚无配置，从模板复制
  if (!fs.existsSync(USER_CONFIG_FILE) && fs.existsSync(path.join(CONFIG_DIR, 'keywords.json'))) {
    try {
      fs.mkdirSync(path.dirname(USER_CONFIG_FILE), { recursive: true });
      fs.copyFileSync(path.join(CONFIG_DIR, 'keywords.json'), USER_CONFIG_FILE);
    } catch (e) { console.error('init config', e); }
  }
  return readJson(USER_CONFIG_FILE);
});
ipcMain.handle('config:write', (_e, obj) => writeJson(USER_CONFIG_FILE, obj));

ipcMain.handle('logs:tail', (_e, name, lines = 300) => {
  const map = {
    auto_daily: 'auto_daily.log',
    crawler: 'crawler.log',
    daily: 'daily_update.log',
    parallel: 'parallel_crawl.log',
    worker: 'parallel_worker.log',
    cleanup: 'stale_cleanup.log',
  };
  const fn = map[name] || name;
  return tailFile(path.join(LOGS_DIR, fn), lines);
});

ipcMain.handle('runner:start', (_e, action) => {
  switch (action) {
    case 'auto_daily':   return spawnPy('auto_daily', 'auto_daily.py');
    case 'one_round':    return spawnPy('one_round', 'daily_update.py');
    case 'parallel_crawl': return spawnPy('parallel_crawl', 'parallel_crawl.py');
    case 'sync_feishu':  return spawnPy('sync_feishu', 'sync_feishu.py');
    case 'stale_cleanup': return spawnPy('stale_cleanup', 'stale_cleanup.py', [], { AI_PM_CHROME_PORT: '9224' });
    // 'login_check' 已废弃：请通过「账号池」面板的「扫码登录」按钮 → boss:manual-login
    default: return { ok: false, error: `未知 action: ${action}` };
  }
});
ipcMain.handle('runner:stop', (_e, key) => killRunner(key));
ipcMain.handle('runner:status', () => getRunnerStatus());

// ------- BOSS 账号池 IPC -------
function readBossAccountsConfig() {
  // 优先读用户工作区，其次读打包/开发目录
  let cfg = readJson(USER_BOSS_ACCOUNTS_FILE);
  if (!cfg) cfg = readJson(PACKAGED_BOSS_ACCOUNTS_FILE);
  if (!cfg) {
    return {
      accounts: [{ alias: '默认', profile_dir: '.chrome_profile', enabled: true }],
      pool_settings: {},
    };
  }
  return cfg;
}

function readAccountPoolSummary() {
  const cfg = readBossAccountsConfig();
  const state = readJson(ACCOUNT_POOL_STATE_FILE) || { accounts: {} };
  const enabled = (cfg.accounts || []).filter(a => a && a.alias && a.enabled !== false);
  const view = enabled.map(acc => {
    const entry = (state.accounts && state.accounts[acc.alias]) || {};
    return {
      alias: acc.alias,
      profile_dir: acc.profile_dir,
      status: entry.status || 'healthy',
      last_ok: entry.last_ok || '',
      last_fail: entry.last_fail || '',
      last_fail_detail: entry.last_fail_detail || '',
      last_used: entry.last_used || '',
      fail_count: entry.fail_count || 0,
      success_count: entry.success_count || 0,
    };
  });
  const allFailed = view.length > 0 && view.every(a => a.status === 'failed');
  return {
    enabled: view.length >= 2,
    current_account: state.current_account || '',
    last_alert_at: state.last_alert_at || '',
    all_failed: allFailed,
    accounts: view,
  };
}

function readParallelPorts() {
  const cfg = readJson(USER_CONFIG_FILE) || readJson(path.join(CONFIG_DIR, 'keywords.json')) || {};
  const ports = cfg.schedule && cfg.schedule.parallel && Array.isArray(cfg.schedule.parallel.ports)
    ? cfg.schedule.parallel.ports
    : [9222, 9223];
  return ports;
}

ipcMain.handle('boss:pool-status', () => readAccountPoolSummary());

ipcMain.handle('boss:manual-login', (_e, alias) => {
  if (!alias || typeof alias !== 'string') {
    return { ok: false, error: '参数 alias 必填' };
  }
  // 已有同名账号登录进程运行 → 拒绝
  const key = `login_${alias}`;
  // 不同账号分配不同 Chrome 调试端口，避免 DrissionPage 复用已有实例
  const cfg = readBossAccountsConfig();
  const idx = (cfg.accounts || []).findIndex(a => a.alias === alias);
  const ports = readParallelPorts();
  const port = ports[Math.max(idx, 0)] || (9222 + Math.max(idx, 0));
  return spawnPy(
    key,
    'login_check.py',
    ['--account', alias, '--interactive'],
    { AI_PM_UNATTENDED: '0', AI_PM_CHROME_PORT: String(port) },
  );
});

ipcMain.handle('boss:stop-manual-login', (_e, alias) => {
  if (!alias) return { ok: false, error: '参数 alias 必填' };
  return killRunner(`login_${alias}`);
});

ipcMain.handle('boss:reset-account', (_e, alias) => {
  // 通过 Python CLI 将指定账号重置为 healthy
  if (!alias || !PY_EXE) return { ok: false, error: '参数缺失或 Python 未检测到' };
  try {
    const script = path.join(SCRIPTS_DIR, 'account_pool.py');
    execSync(`"${PY_EXE}" "${script}" reset "${alias}"`, {
      cwd: REPO_ROOT, timeout: 5000, stdio: 'ignore',
      env: { ...process.env, AI_PM_BASE_DIR: REPO_ROOT, PYTHONIOENCODING: 'utf-8' },
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e).slice(0, 200) };
  }
});

// ------- 飞书告警 IPC -------
const ENV_FILE = path.join(REPO_ROOT, '.env');
const FEISHU_ALERT_STATE_FILE = path.join(LOGS_DIR, 'feishu_alert_state.json');

function readEnvFile() {
  // 返回 .env 的 key -> value 映射（不做任何解密/脱敏，仅在主进程使用）
  const out = {};
  if (!fs.existsSync(ENV_FILE)) return out;
  try {
    const text = fs.readFileSync(ENV_FILE, 'utf-8');
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const idx = line.indexOf('=');
      const k = line.slice(0, idx).trim();
      const v = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
      if (k) out[k] = v;
    }
  } catch (_) { /* ignore */ }
  return out;
}

function readFeishuStatus() {
  const env = readEnvFile();
  const alertEnv = process.env; // 也兜底看系统环境变量
  const webhook = (env.FEISHU_ALERT_WEBHOOK || alertEnv.FEISHU_ALERT_WEBHOOK || '').trim();
  const secret = (env.FEISHU_ALERT_SECRET || alertEnv.FEISHU_ALERT_SECRET || '').trim();
  const state = readJson(FEISHU_ALERT_STATE_FILE) || {};

  const webhookOk = webhook.startsWith('https://open.feishu.cn/open-apis/bot/v2/hook/');

  // 从 state 里摘出每个 alert_key 的 last_sent_at / total_sent
  const entries = Object.entries(state).map(([key, v]) => ({
    key,
    last_sent_at: (v && v.last_sent_at) || '',
    total_sent: (v && v.total_sent) || 0,
  }));

  return {
    configured: webhookOk,
    has_webhook: !!webhook,
    webhook_valid: webhookOk,
    has_secret: !!secret,
    alerts: entries,
  };
}

function runFeishuCommand(flag, timeoutMs = 15000) {
  if (!PY_EXE) return { ok: false, error: '未检测到 Python 3' };
  const script = path.join(SCRIPTS_DIR, 'feishu_alert.py');
  try {
    const out = execSync(`"${PY_EXE}" "${script}" ${flag}`, {
      cwd: REPO_ROOT,
      timeout: timeoutMs,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, AI_PM_BASE_DIR: REPO_ROOT, PYTHONIOENCODING: 'utf-8' },
    });
    return { ok: true, stdout: String(out || '').slice(-400) };
  } catch (e) {
    const stderr = (e.stderr ? String(e.stderr) : '') || (e.stdout ? String(e.stdout) : '') || String(e.message || e);
    return { ok: false, error: stderr.slice(-400) };
  }
}

ipcMain.handle('feishu:status', () => readFeishuStatus());
ipcMain.handle('feishu:test', () => runFeishuCommand('--test'));
ipcMain.handle('feishu:test-alert', () => runFeishuCommand('--test-alert'));
ipcMain.handle('feishu:test-report', () => runFeishuCommand('--test-report'));
ipcMain.handle('feishu:reset-throttle', () => runFeishuCommand('--reset-throttle'));

// ------- 数据清洗 IPC -------
const CLEANUP_RECORD_FILE = path.join(LOGS_DIR, 'cleanup_record.json');

ipcMain.handle('cleanup:status', () => {
  const records = readJson(CLEANUP_RECORD_FILE) || [];
  const last = records.length > 0 ? records[records.length - 1] : null;
  // 读取配置中的间隔
  let interval = 3;
  try {
    const cfg = readJson(path.join(CONFIG_DIR, 'keywords.json')) || {};
    interval = (cfg.schedule || {}).cleanup_interval_days || 3;
  } catch (_) {}
  return { last, interval, history: records.slice(-5).reverse() };
});

ipcMain.handle('shell:open-external', (_e, url) => shell.openExternal(url));
ipcMain.handle('shell:open-folder', (_e, which) => {
  const map = { repo: REPO_ROOT, logs: LOGS_DIR, config: CONFIG_DIR };
  shell.openPath(map[which] || REPO_ROOT);
});

// 轮询 progress.json + run_status.json + 账号池状态 推送到前端
setInterval(() => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const p = readJson(PROGRESS_FILE);
  const s = readJson(STATUS_FILE);
  const pool = readAccountPoolSummary();
  broadcast('tick', { progress: p, status: s, pool });
}, 2000);

// ------- Single instance lock -------
// 双击桌面快捷方式多次时，聚焦已有窗口而不是再开一个
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ------- App lifecycle -------
app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  // 停止所有子进程
  Object.keys(runners).forEach(k => { try { killRunner(k); } catch {} });
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  Object.keys(runners).forEach(k => { try { killRunner(k); } catch {} });
});
