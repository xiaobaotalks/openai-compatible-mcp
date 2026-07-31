<div align="center">

# 🤖 openai-compatible-mcp

**一个 [MCP](https://modelcontextprotocol.io) 服务器,桥接到任何 OpenAI 兼容的 Chat API**

[![Version](https://img.shields.io/badge/version-0.2.22-blue?style=for-the-badge)](https://pypi.org/project/openai-compatible-mcp/)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/openai-compatible-mcp/)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-install-orange?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/openai-compatible-mcp/)

[![Stars](https://img.shields.io/github/stars/xiaobaotalks/openai-compatible-mcp?style=social)](https://github.com/xiaobaotalks/openai-compatible-mcp)
[![Issues](https://img.shields.io/github/issues/xiaobaotalks/openai-compatible-mcp?style=social)](https://github.com/xiaobaotalks/openai-compatible-mcp/issues)

[English](README.en.md) · [快速开始](#快速开始) · [代理模式](#代理模式codex--第三方客户端) · [PyPI](https://pypi.org/project/openai-compatible-mcp/)

</div>

---

## ✨ 特性

| 特性 | 说明 |
|:---:|:---|
| 🪶 **零依赖** | 仅用 Python 3.9+ 标准库,无需 `pip install` 第三方包 |
| 🔌 **万能兼容** | DeepSeek · OpenAI · Azure · OpenRouter · Together · Groq · llama.cpp |
| 🎯 **模型别名** | `deepseek-v4-flash` → `deepseek-v4-flash` 等智能映射 |
| 🧠 **推理提取** | 自动提取 `<think>...</think>` 中的 reasoning 内容 |
| 🔄 **双模式** | MCP stdio + 直接 HTTP `/v1/chat/completions` |
| 🌐 **Web UI** | 浏览器可视化配置,热更新无需重启 |
| 🖥️ **后台代理** | `--background` 后台运行,`--status`/`--stop` 管理 |
| 📦 **极简代码** | ~400 行核心代码 |

## 🏗️ 架构

```
┌──────────────────┐    stdio JSON-RPC    ┌─────────────────────┐
│  Claude Desktop   │ ───────────────────▶│                     │
│  Cursor / VSCode  │                     │  openai-compatible  │
│  Claude Code      │                     │  -mcp               │
└──────────────────┘                     │                     │
                                         │  ┌───────────────┐  │
┌──────────────────┐   HTTP /v1/chat/... │  │  翻译代理      │  │
│  Codex CLI 0.140+ │ ───────────────────▶│  │  127.0.0.1    │  │
│  (直连 API)       │                     │  │    :7878      │  │
└──────────────────┘                     │  └──────┬────────┘  │
                                         │         │           │
┌──────────────────┐   http://127/8989   │         ▼           │
│  你的浏览器        │ ───────────────────▶│  上游 API          │
│  (向导 UI)        │      一次性配置      │  (DeepSeek 等)     │
└──────────────────┘                     └─────────────────────┘
```

---

## 🚀 快速开始

### 方式 A:一键安装向导(推荐)

双击 `setup\install.bat`(Windows)或运行 `./setup/install.sh`(macOS / Linux),
浏览器会自动打开图形化向导。选 provider、填 API key、勾选客户端,一键配置。

详细文档见 [setup/README.md](setup/README.md)。

### 方式 B:命令行

```bash
pip install openai-compatible-mcp

# 两种等价命令
openai-compatible-mcp --help
xbcode --help
```

### 配置 API Key

```bash
# DeepSeek (默认)
export DEEPSEEK_API_KEY="sk-..."

# 其他兼容端点
export OPENAI_COMPATIBLE_MCP_API_KEY="..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://my-endpoint.com"
export OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL="my-model"
```

| 设置项 | 查找顺序(第一个非空胜出) |
|:---|:---|
| API Key | `OPENAI_COMPATIBLE_MCP_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` |
| Base URL | `OPENAI_COMPATIBLE_MCP_BASE_URL` → `DEEPSEEK_API_BASE` → `OPENAI_BASE_URL` |
| 默认模型 | `OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL` → `DEEPSEEK_DEFAULT_MODEL` |

### 接入 MCP 客户端

**Claude Desktop / Cursor:**

```json
{
  "mcpServers": {
    "openai-compatible": {
      "command": "python",
      "args": ["-m", "openai_compatible_mcp"],
      "env": { "DEEPSEEK_API_KEY": "sk-..." }
    }
  }
}
```

---

## 🛠️ 工具

### `chat` — 对话补全

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---:|:---|
| `messages` | array | ✅ | `{role, content}` 消息列表 |
| `model` | string | | 模型名或别名 |
| `temperature` | number | | 0-2,越小越确定 |
| `max_tokens` | integer | | 最大生成 token 数 |
| `system` | string | | 系统提示 |
| `include_reasoning` | boolean | | 包含 `<think>` 推理内容 |

**示例:**

```json
{
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "messages": [{"role": "user", "content": "写一首关于 Python 的俳句。"}],
      "model": "deepseek-v4-flash",
      "temperature": 0.7
    }
  }
}
```

### `list_models` — 列出模型

返回默认模型和完整的别名映射表。

---

## 🎨 模型别名

| 别名 | 解析为 |
|:---|:---|
| `deepseek-v4-pro` | `deepseek-v4-pro` |
| `deepseek-v4-flash` | `deepseek-v4-flash` |
| `deepseek-reasoner` | `deepseek-reasoner` |
| `deepseek-r1` | `deepseek-reasoner` |
| `gpt-4o` | `gpt-4o` |
| `o1-mini` | `o1-mini` |

不在别名表中的模型名会原样透传,provider 发布新模型可直接使用。

---

## 🔀 代理模式(Codex / 第三方客户端)

当使用 Codex CLI 等需要 **Responses API** (`/v1/responses`) 的客户端时,
`openai-compatible-mcp` 启动翻译代理将 Responses API → Chat Completions → Responses。

### 前台运行

```bash
xbcode --proxy
xbcode --proxy --api-key sk-你的key
```

代理默认监听 `http://127.0.0.1:7878`:
- `POST /responses` → 翻译为 DeepSeek 请求并返回 Responses 格式
- `GET /v1/models` → 模型别名列表
- `GET /health` → 健康检查

### 后台运行 (v0.2.22+)

```bash
# 后台启动
xbcode --proxy --background

# 查看状态(PID + 日志)
xbcode --status

# 停止
xbcode --stop
```

后台文件: `~/.openai-compatible-mcp/proxy.pid` · `~/.openai-compatible-mcp/proxy.log`

### Web UI

浏览器打开 `http://127.0.0.1:7878/`:
- 📋 查看当前配置
- ✏️ 修改 API Key / Base URL (热更新,无需重启)
- 🎛️ 编辑模型别名映射

---

## 🧪 测试

```bash
# 单元测试
python -m pytest tests/test_unit.py -v

# 冒烟测试
PYTHONPATH=src python tests/smoke_test.py
```

---

## 📁 项目结构

```
openai-compatible-mcp/
├── src/openai_compatible_mcp/
│   ├── __main__.py        # CLI 入口
│   ├── __init__.py        # MCP server + JSON-RPC
│   ├── client.py          # API 调用封装
│   └── proxy_server.py    # Responses ↔ Chat 翻译代理
├── tests/
│   ├── test_unit.py       # 单元测试
│   └── smoke_test.py      # 冒烟测试
├── setup/                 # 一键安装向导
└── pyproject.toml
```

---

## 📜 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解完整变更历史。

**v0.2.22 亮点:**
- 🆕 `xbcode` 命令别名
- 🆕 代理后台模式 (`--background` / `--status` / `--stop`)
- 🐛 代理配置热更新修复
- 🐛 移除 `globals()` 污染
- ⚡ 优雅退出与信号处理

---

## 🤝 贡献

欢迎 Issue 和 PR!

## 📄 协议

MIT License — 见 [LICENSE](LICENSE)。
