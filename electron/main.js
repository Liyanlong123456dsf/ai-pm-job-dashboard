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
    ['keywords.json'].forEach(f => {
      const src = path.join(process.resourcesPath, 'config', f);
      const dst = path.join(userConfig, f);
      if (fs.existsSync(src)) fs.copyFileSync(src, dst);
    });
  }
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
  };
  const fn = map[name] || name;
  return tailFile(path.join(LOGS_DIR, fn), lines);
});

ipcMain.handle('runner:start', (_e, action) => {
  switch (action) {
    case 'auto_daily':   return spawnPy('auto_daily', 'auto_daily.py');
    case 'one_round':    return spawnPy('one_round', 'daily_update.py');
    case 'login_check':  return spawnPy('login_check', 'login_check.py');
    case 'sync_feishu':  return spawnPy('sync_feishu', 'sync_feishu.py');
    default: return { ok: false, error: `未知 action: ${action}` };
  }
});
ipcMain.handle('runner:stop', (_e, key) => killRunner(key));
ipcMain.handle('runner:status', () => getRunnerStatus());

ipcMain.handle('shell:open-external', (_e, url) => shell.openExternal(url));
ipcMain.handle('shell:open-folder', (_e, which) => {
  const map = { repo: REPO_ROOT, logs: LOGS_DIR, config: CONFIG_DIR };
  shell.openPath(map[which] || REPO_ROOT);
});

// 轮询 progress.json + run_status.json 推送到前端
setInterval(() => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const p = readJson(PROGRESS_FILE);
  const s = readJson(STATUS_FILE);
  broadcast('tick', { progress: p, status: s });
}, 2000);

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
