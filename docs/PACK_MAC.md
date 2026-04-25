# macOS 打包指南

> 在 **macOS** 机器上将 AI PM Job Dashboard 打包为 `.dmg` / `.app` 的完整指南。
> Windows 机器**无法**打包 Mac 产物（electron-builder 需要 macOS 原生工具链，如 `hdiutil`、`codesign`）。

---

## 🧰 前置条件

| 组件 | 版本 | 获取方式 |
|------|------|---------|
| macOS | 10.15+ | — |
| Node.js | 18 LTS 或 20 LTS | `brew install node@20` 或 [官网](https://nodejs.org/) |
| npm | ≥ 9 | 随 Node 安装 |
| Python | 3.10+ | `brew install python@3.11` |
| Xcode Command Line Tools | 最新 | `xcode-select --install` |

验证：
```bash
node -v    # v20.x
npm -v     # 10.x
python3 -V # 3.10+
xcode-select -p  # 输出 /Library/Developer/CommandLineTools
```

---

## 🚀 一键打包（推荐）

```bash
# 1. 克隆源码（若未克隆）
git clone https://github.com/Liyanlong123456dsf/ai-pm-job-dashboard.git
cd ai-pm-job-dashboard

# 2. 安装依赖
npm install
pip3 install -r requirements.txt   # Python 依赖可选，仅 electron 本身不需要

# 3. 打包 DMG（arm64 + x64 双架构）
npm run pack:mac
```

也可以双击项目根目录的 `launcher/pack-mac.command` 脚本（效果一致）。

### 产物位置

```
release/
├── AI PM Job Dashboard-1.0.0-macOS-arm64.dmg    # Apple Silicon (M1/M2/M3)
├── AI PM Job Dashboard-1.0.0-macOS-x64.dmg      # Intel Mac
├── mac-arm64/AI PM Job Dashboard.app             # 未压缩 app（arm64）
└── mac/AI PM Job Dashboard.app                   # 未压缩 app（x64）
```

---

## 🎯 分架构打包

只打一种架构以减少构建时间：

```bash
# 仅 Apple Silicon
npx electron-builder --mac --arm64

# 仅 Intel
npx electron-builder --mac --x64

# 通用二进制（单 dmg 含双架构，体积翻倍）
npx electron-builder --mac --universal
```

---

## 📦 仅产出 `.app`（不压成 dmg）

如果不想要 dmg，只想要裸 `.app` 目录：

```bash
npm run portable:mac
# 产物: release/AI PM Job Dashboard-darwin-arm64/
#       release/AI PM Job Dashboard-darwin-x64/
```

然后手动 `tar czf` 或 `zip -r` 压缩分发。

---

## 🔐 代码签名与公证（可选）

**默认配置**（`package.json` 里）：
```json
"mac": {
  "hardenedRuntime": false,
  "gatekeeperAssess": false
}
```
即**不做代码签名和公证**，用户下载后会遇到 Gatekeeper 警告"应用已损坏"或"无法打开，因为无法验证开发者"。

### 让用户绕过 Gatekeeper（最简单）

在用户的 README/下载页加一句：

> **首次打开**：请右键点击 app 图标 → 选择「打开」 → 在弹窗中点「打开」。
> 或在终端执行：
> ```bash
> xattr -cr "/Applications/AI PM Job Dashboard.app"
> ```

### 正规签名（可选，需付费）

1. 申请 Apple Developer Program（$99/年）
2. 在 Keychain 里导入 "Developer ID Application" 证书
3. 在 `package.json` 里改：
   ```json
   "mac": {
     "hardenedRuntime": true,
     "gatekeeperAssess": true,
     "identity": "Developer ID Application: Your Name (TEAMID)"
   }
   ```
4. 设环境变量后打包：
   ```bash
   export CSC_LINK=~/path/to/DeveloperIDApplication.p12
   export CSC_KEY_PASSWORD='your-p12-password'
   npm run pack:mac
   ```
5. 公证（需在 Apple ID 里生成 app-specific password）：
   ```bash
   export APPLE_ID='your@apple.id'
   export APPLE_APP_SPECIFIC_PASSWORD='xxxx-xxxx-xxxx-xxxx'
   export APPLE_TEAM_ID='TEAMID'
   npm run pack:mac   # 会自动触发公证
   ```

---

## 🧪 本地测试

```bash
# 启动（不打包，快速验证）
npm run start

# 或启动打包后的 app
open "release/mac-arm64/AI PM Job Dashboard.app"
```

---

## 🐛 常见问题

### 1. `Python 3.x is not installed` 错误
Electron 应用在 macOS 上通过 `which python3` 探测 Python。若用户 `$PATH` 里没 python3：
- 指导用户 `brew install python@3.11`
- 或在 app 内「设置」里手动指定 Python 路径（`electron/main.js` 的 `detectPython()` 支持）

### 2. arm64/Intel app 在另一架构上无法启动
- arm64 app 无法在 Intel Mac 上启动
- 如果用户群体不确定，建议发 **universal** 版本（`--universal`）
- 或同时发两份 dmg，在下载页分别标注

### 3. 打包报错 `Could not find asar binary`
```bash
rm -rf node_modules
npm install
```

### 4. dmg 打包卡在 `hdiutil`
通常是 `release/` 里已有同名挂载未释放：
```bash
hdiutil detach /Volumes/AI\ PM\ Job\ Dashboard* -force
rm -rf release
npm run pack:mac
```

### 5. 打包后的 app 无法调用 Python 子进程
确认 `electron/main.js` 的 Python 探测逻辑已包含 macOS 分支（`platform === 'darwin'`），并且 `scripts/**/*.py` 在 `package.json` 的 `extraResources` 配置里：

```json
"extraResources": [
  { "from": "scripts", "to": "scripts", "filter": ["**/*.py"] },
  { "from": "config", "to": "config" }
]
```

---

## 📤 GitHub Releases 发布

```bash
git tag v1.0.0
git push origin v1.0.0
```

然后在 GitHub 网页创建 Release，上传：
- `release/AI PM Job Dashboard-1.0.0-macOS-arm64.dmg`
- `release/AI PM Job Dashboard-1.0.0-macOS-x64.dmg`
- Windows 产物（`.exe` / `.zip`）

---

## 📝 用户下载页文案（可直接复制）

```markdown
### Mac 用户安装

1. 根据自己的机型下载对应 dmg：
   - **M1/M2/M3 (Apple Silicon)** → `AI-PM-Job-Dashboard-1.0.0-macOS-arm64.dmg`
   - **Intel Mac** → `AI-PM-Job-Dashboard-1.0.0-macOS-x64.dmg`
   - 不确定？选 arm64（近几年大部分 Mac 都是 Apple Silicon）
2. 双击 dmg，将 app 拖到「应用程序」
3. **首次打开**：右键点击 app → 选「打开」→「打开」（绕过 Gatekeeper）
   - 如提示"已损坏"：终端执行 `xattr -cr "/Applications/AI PM Job Dashboard.app"`
4. 爬虫功能需 Python 3.10+：`brew install python@3.11`
5. 首次启动会自动 `pip3 install -r requirements.txt`（约 2 分钟）
```

---

## 🔗 参考

- [electron-builder Mac 配置](https://www.electron.build/configuration/mac)
- [macOS 代码签名与公证](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- 项目 `package.json` 的 `build.mac` 段
