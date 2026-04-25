# 发布与分发指南

## 🎁 分发方式速查

| 分发对象 | 推荐方式 | 所需文件 |
|---------|----------|---------|
| **非技术用户** | 发 zip/安装包 | `release/AI-PM-Job-Dashboard-win32-x64/` 整个文件夹 |
| **Mac 用户** | 发 .dmg | `release/AI-PM-Job-Dashboard-darwin-*/` |
| **开发者** | GitHub 仓库链接 | README.md 已包含源码编译指南 |
| **只看数据** | GitHub Pages | `job_dashboard.html`（在线访问，无需下载） |

---

## 📦 Windows 打包（已完成 ✅）

当前产物：`release/AI-PM-Job-Dashboard-win32-x64/`（约 280MB）

### 打包步骤
```powershell
# 开发机（本电脑）执行
$env:Path += ";C:\Program Files\nodejs"
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
npm run portable:win
```

### 分发给他人

**方案 A：打包成 zip**
```powershell
Compress-Archive -Path release\AI-PM-Job-Dashboard-win32-x64 `
                 -DestinationPath release\AI-PM-Job-Dashboard-Windows-v1.0.0.zip
```

**方案 B：做成安装包**（需解决 symlink 权限问题，参考下方）

---

## 🍎 macOS 打包（需在 Mac 上执行）

### 前置
```bash
# Mac 电脑
brew install node python
git clone https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard.git
cd ai-pm-job-dashboard
npm install
```

### 打包 DMG（需 electron-builder）
```bash
npm run pack:mac
# 产物: release/AI-PM-Job-Dashboard-1.0.0-macOS-arm64.dmg (Apple Silicon)
#       release/AI-PM-Job-Dashboard-1.0.0-macOS-x64.dmg (Intel)
```

### 打包为文件夹（electron-packager）
```bash
npm run portable:mac
# 产物: release/AI PM Job Dashboard-darwin-arm64/
#       release/AI PM Job Dashboard-darwin-x64/
```

### 签名问题
macOS 会提示「应用无法打开」，因为没有开发者签名。让用户：
1. 右键点击 app → 选「打开」
2. 或在终端执行 `xattr -cr "/Applications/AI PM Job Dashboard.app"`

---

## 🚀 GitHub Releases 发布

```bash
# 1. 创建 git tag
git tag v1.0.0
git push origin v1.0.0

# 2. 在 GitHub 网页上传产物:
# https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard/releases/new
#
# 上传以下文件:
# - AI-PM-Job-Dashboard-Windows-v1.0.0.zip
# - AI-PM-Job-Dashboard-macOS-arm64-v1.0.0.dmg
# - AI-PM-Job-Dashboard-macOS-x64-v1.0.0.dmg
```

---

## 💡 Windows NSIS 安装包（可选，需解决 symlink）

遇到 `Cannot create symbolic link` 错误？有三种解决方案：

### 方案 1：启用 Developer Mode（推荐）
Windows 设置 → 更新与安全 → 开发者选项 → 打开「开发人员模式」，然后：
```powershell
npm run pack:win
```

### 方案 2：以管理员身份运行
右键 PowerShell → 「以管理员身份运行」 → 执行 `npm run pack:win`

### 方案 3：禁用代码签名
直接用 `npm run portable:win`（已验证可用）

---

## 🛠 接收者使用说明（直接贴给用户）

### Windows 用户

1. 下载 `AI-PM-Job-Dashboard-Windows-v1.0.0.zip`
2. 解压到任意目录（如 `D:\AIPMDashboard\`）
3. 双击 `AI-PM-Job-Dashboard.exe` 启动
4. **爬取功能需本地已装 Python 3.10+**，安装后重启应用

### macOS 用户

1. 下载 `.dmg` 文件
2. 双击打开，拖动 app 到 `应用程序`
3. 首次打开右键 → 选「打开」（绕过 Gatekeeper）
4. **爬取功能需 Python 3.10+**：`brew install python`

---

## 📊 Python 依赖检查

应用启动后若看到 "未检测到 Python"，用户需执行：

**Windows:**
```powershell
python -m pip install -r requirements.txt
```

**macOS:**
```bash
python3 -m pip install -r requirements.txt
```

或在控制台 → 系统信息 中查看 Python 状态。
