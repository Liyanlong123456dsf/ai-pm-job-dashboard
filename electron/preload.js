/**
 * Preload: 暴露受限 API 给渲染进程（安全隔离）
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  // 系统信息
  sysInfo: () => ipcRenderer.invoke('sys:info'),

  // 数据
  getJobs: () => ipcRenderer.invoke('data:jobs'),
  getStatus: () => ipcRenderer.invoke('data:status'),
  getProgress: () => ipcRenderer.invoke('data:progress'),
  getRecords: () => ipcRenderer.invoke('data:records'),

  // 配置
  readConfig: () => ipcRenderer.invoke('config:read'),
  writeConfig: (obj) => ipcRenderer.invoke('config:write', obj),

  // 日志
  tailLog: (name, lines) => ipcRenderer.invoke('logs:tail', name, lines),

  // 运行控制
  startRunner: (action) => ipcRenderer.invoke('runner:start', action),
  stopRunner: (key) => ipcRenderer.invoke('runner:stop', key),
  runnerStatus: () => ipcRenderer.invoke('runner:status'),

  // 壳层
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  openFolder: (which) => ipcRenderer.invoke('shell:open-folder', which),

  // 事件订阅
  onRunnerLog: (cb) => {
    const h = (_e, data) => cb(data);
    ipcRenderer.on('runner:log', h);
    return () => ipcRenderer.removeListener('runner:log', h);
  },
  onRunnerStatus: (cb) => {
    const h = (_e, data) => cb(data);
    ipcRenderer.on('runner:status', h);
    return () => ipcRenderer.removeListener('runner:status', h);
  },
  onTick: (cb) => {
    const h = (_e, data) => cb(data);
    ipcRenderer.on('tick', h);
    return () => ipcRenderer.removeListener('tick', h);
  },
});
