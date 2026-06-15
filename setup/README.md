# openai-compatible-mcp 一键安装向导

把任意 OpenAI 兼容的 API(DeepSeek、OpenAI、Azure、OpenRouter、Groq、本地 llama.cpp 等)
接入 **Claude Desktop / Cursor / Claude Code / Codex** 的图形化向导。

完全本地运行,不发送任何数据到外网(除了你自己选的 provider)。

## 一键启动

### Windows — 方式一（推荐：完全自动）

双击 `install-oneclick.bat`，自动完成所有步骤（检测 Python、安装包、写入配置文件、显示说明），无需手动输入任何命令。

```
setup\
├── install-oneclick.bat  ← 双击这个（推荐）
└── install.bat           ← 图形化向导（需要浏览器）
```

### Windows — 方式二（图形化向导）

1. 双击 `setup\install.bat`
2. 浏览器自动打开 `http://127.0.0.1:8989`，跟着点就行

或者在 PowerShell 里:

```powershell
cd path\to\openai-compatible-mcp\setup
.\install.bat
```

### macOS / Linux

```bash
cd path/to/openai-compatible-mcp/setup
chmod +x install.sh
./install.sh
```

## 流程

### install-oneclick.bat（全自动）

1. **检测 Python** — 查找常见安装路径，提示用户安装如未找到
2. **安装包** — `pip install -e .`（editable 模式）
3. **环境自检** — 检测模块可加载性、API Key 配置情况
4. **写入配置** — 自动写入所有目标客户端的配置文件（合并式，不破坏现有配置）
5. **显示说明** — 告知用户如何使用

### install.bat（向导式）

1. **检查环境** - 检测 Python、pip、当前包状态
2. **一键安装** - 从 PyPI 拉取 `openai-compatible-mcp`
3. **填 API key** - 选 DeepSeek/OpenAI/Azure/...,粘贴 key,测试连接
4. **选客户端** - 勾选已安装的 Claude Desktop / Cursor / Claude Code / Codex
5. **一键写入配置** - 自动修改对应配置文件
6. **完成** - 重启客户端,搞定

## 截图(假装有)

```
┌─────────────────────────────────────────────┐
│   你的 MCP, 一键接入 任何 OpenAI 兼容 API    │
│                                              │
│   ① 检查环境                                 │
│      ✓ Python 3.12.1                        │
│      ✓ pip 25.0.1                           │
│      ✗ openai-compatible-mcp  未安装         │
│                                              │
│   ② 安装 / 升级包                            │
│      [一键安装 openai-compatible-mcp]        │
│                                              │
│   ③ 配置 API 提供商                          │
│      提供商: [DeepSeek        ▼]             │
│      API Key: [sk-...                  ]     │
│      模型名:  [deepseek-v4-pro       ]       │
│      [测试连接]  ✓ 连接正常                  │
│                                              │
│   ④ 选择客户端                               │
│      [x] Claude Desktop                     │
│      [x] Cursor                             │
│      [ ] Claude Code                        │
│      [ ] Codex CLI                          │
│                                              │
│   ⑤ 写入配置                                 │
│      [一键写入配置]                          │
│                                              │
│   ⑥ 完成 ✓                                   │
│      重启客户端即可使用                       │
└─────────────────────────────────────────────┘
```

## 配置文件位置

| 客户端         | 配置文件                                              |
| -------------- | ----------------------------------------------------- |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (Win)   |
|                | `~/Library/Application Support/Claude/...` (macOS)    |
|                | `~/.config/Claude/...` (Linux)                        |
| Cursor         | `~/.cursor/mcp.json`                                  |
| Claude Code    | `~/.claude.json` + `~/.claude/settings.json`              |
| Codex          | `~/.codex/config.toml`                                |

## 配置写入是合并式的

向导**不会**覆盖你现有的 MCP 配置,只会把 `openai-compatible` 这一个 server
加到 `mcpServers` 字段下,其他 server 都保留。

## Claude Code 跳过登录

Claude Code 启动时会检查 `~/.claude.json`，如果存在 `hasCompletedOnboarding: true` 则跳过登录引导。`install-oneclick.bat` 会自动写入该文件，同时在 `~/.claude/settings.json` 中设置 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`，将 API 请求路由到 DeepSeek。

> **注意**：Claude Code 2025 年后版本强制要求 OAuth 登录，纯配置文件可能无法完全绕过登录。此时需要借助 CC Switch 等本地代理工具（原理是将所有请求劫持到第三方服务器，使 Claude Code 无法连接官方登录接口），详见 [CC Switch 使用教程](https://docs.apiyi.com/scenarios/programming/cc-switch)。

## 配置文件示例

写完之后的 `claude_desktop_config.json` 大概长这样:

```json
{
  "mcpServers": {
    "openai-compatible": {
      "command": "uvx",
      "args": ["openai-compatible-mcp"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-...",
        "OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL": "deepseek-v4-pro"
      }
    },
    "your-other-server": { "...": "..." }
  }
}
```

## 常见问题

### 端口 8989 被占用

杀掉占用进程:

```powershell
# Windows
Get-NetTCPConnection -LocalPort 8989 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 选 uvx 但没装 uv

```powershell
winget install astral-sh.uv
```

或者在向导第 ④ 步把启动方式从 `uvx` 改成 `python -m openai_compatible_mcp`(无需额外工具)。

### Codex 配置项

Codex CLI 走 OpenAI Responses API,而 DeepSeek/大多数 provider 只暴露
Chat Completions API。向导会写一个 `model_providers.openai_compatible_mcp`
块到 `~/.codex/config.toml`,但你仍然需要先跑一下 `proxy/server.py`(我们
项目的最初版本)做协议转换,或者直接用 `chat` 工具调用。详见主 README。

### 修改后想重新配置

向导的所有配置都是**幂等**的,可以反复运行。

## 安全

- API key **仅**写入本机的 `claude_desktop_config.json` / `mcp.json` /
  `~/.claude.json` / `~/.codex/config.toml`,**不上传**任何服务
- 端口 8989 **只绑定** `127.0.0.1`,不暴露到局域网或公网
- `install.bat` 不会修改任何全局设置,只在当前用户的计划任务里登记一个
  可选的"开机启动本向导"项(默认**不开启**)

## 开发

```bash
cd setup
python server.py
# 浏览器打开 http://127.0.0.1:8989
```

修改 `index.html` 后刷新浏览器即可。修改 `server.py` 后需要 Ctrl+C 重启。
