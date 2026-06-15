# openai-compatible-mcp

> English version: [README.en.md](README.en.md) · 反馈问题:[Issues](https://github.com/xiaobaotalks/openai-compatible-mcp/issues)

一个 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 服务器,
桥接到任何 **OpenAI 兼容的 chat API** —— DeepSeek、OpenAI、Azure OpenAI、
OpenRouter、Together、Groq、本地 llama.cpp 等。

> **默认 provider:** DeepSeek。通过单个环境变量即可切换到任何 OpenAI 兼容端点。

## 功能

- **零三方依赖**(Python 3.9+ 标准库)
- 支持**任何** OpenAI 兼容 chat API
- 友好的模型别名(`deepseek-v4-flash` → `deepseek-v4-flash`,`r1` → `deepseek-reasoner` 等)
- 可选的 reasoning 内容提取(DeepSeek-R1 风格)
- 自实现 JSON-RPC 2.0 over stdio MCP 传输
- 代码量小:~400 行

## 快速开始

### 方式 A:一键安装向导(推荐,傻瓜式)

双击 `setup\install.bat`(Windows)或运行 `./setup/install.sh`(macOS / Linux),
浏览器会自动打开一个图形化向导。选 provider、填 API key、勾选要配置的客户端,
点"一键写入配置"就完了。向导会:

1. 检测 Python / pip / 包状态
2. 从 PyPI 拉取 / 升级包
3. 测试到你选 provider 的连接
4. 为 Claude Desktop / Cursor / Claude Code / Codex **分别**写入配置
   (其他 server 配置不会被覆盖)
5. 可选:设置开机自启

详细文档见 [setup/README.md](setup/README.md)。

### 方式 B:命令行

#### 1. 安装

从源码:

```bash
git clone https://github.com/xiaobaotalks/openai-compatible-mcp.git
cd openai-compatible-mcp
pip install -e .
```

或者不安装直接跑:

```bash
PYTHONPATH=src python -m openai_compatible_mcp
```

#### 2. 配置

设置你的 API key(可选地设置 base URL):

```bash
# DeepSeek(默认)
export DEEPSEEK_API_KEY="sk-..."

# OpenAI
export OPENAI_API_KEY="sk-..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://api.openai.com"

# Azure OpenAI
export OPENAI_COMPATIBLE_MCP_API_KEY="..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT"

# 本地 llama.cpp server
export OPENAI_COMPATIBLE_MCP_BASE_URL="http://127.0.0.1:8080"
export OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL="llama-3.1-8b"

# 自定义:任何兼容 OpenAI /v1/chat/completions 的端点
export OPENAI_COMPATIBLE_MCP_API_KEY="..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://my.example.com"
export OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL="my-model"
```

环境变量查找顺序(第一个非空的胜出):

| 设置项      | 依次尝试的变量                                                            |
| ----------- | ------------------------------------------------------------------------- |
| API key     | `OPENAI_COMPATIBLE_MCP_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`   |
| Base URL    | `OPENAI_COMPATIBLE_MCP_BASE_URL` → `DEEPSEEK_API_BASE` → `OPENAI_BASE_URL` |
| 默认模型    | `OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL` → `DEEPSEEK_DEFAULT_MODEL`          |

### 3. 接入 MCP 客户端

#### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
或 `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "openai-compatible": {
      "command": "python",
      "args": ["-m", "openai_compatible_mcp"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

完整示例见 `examples/claude_desktop_config.json`。

#### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "openai-compatible": {
      "command": "python",
      "args": ["-m", "openai_compatible_mcp"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

#### Claude Code / 其他 stdio 客户端

同样格式:把 `python -m openai_compatible_mcp` 启动为子进程,stdin/stdout 走 JSON-RPC。

## 工具

### `chat`

向配置好的 provider 发送 chat completion。

| 字段                | 类型            | 必填 | 说明                                                          |
| ------------------- | --------------- | ---- | ------------------------------------------------------------- |
| `messages`          | array           | 是   | `{role, content}` 消息列表(从旧到新)。                        |
| `model`             | string          | 否   | 模型名或别名(如 `deepseek-v4-flash`、`o1-mini`)。             |
| `temperature`       | number          | 否   | 0-2,越小越确定。                                              |
| `max_tokens`        | integer         | 否   | 最大生成 token 数。                                           |
| `top_p`             | number          | 否   | nucleus 采样阈值。                                            |
| `stop`              | string \| array | 否   | 停止序列。                                                    |
| `system`            | string          | 否   | 系统提示(插入到对话最前面)。                                 |
| `include_reasoning` | boolean         | 否   | 把 reasoning 内容包在 `<think>...</think>` 中返回。           |

**示例**(来自 MCP 客户端):

```json
{
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "messages": [
        {"role": "user", "content": "写一首关于 Python 的俳句。"}
      ],
      "model": "deepseek-v4-flash",
      "temperature": 0.7
    }
  }
}
```

工具返回文本内容,包含助手回复 + 使用统计:

```
缩进如春叶绽放,
代码在光标间流淌——
Bug 化作一行诗。

---
model: deepseek-v4-pro | prompt_tokens: 12 | completion_tokens: 28 | total_tokens: 40
```

### `list_models`

返回默认模型和别名表。

## 内置模型别名

你可以在 `src/openai_compatible_mcp/client.py` 里增删别名。默认:

| 别名                 | 解析为                |
| -------------------- | --------------------- |
| `deepseek-v4-pro`    | `deepseek-v4-pro`     |
| `deepseek-v4-flash`  | `deepseek-v4-flash`   |
| `deepseek-v3`        | `deepseek-v4-pro`     |
| `deepseek-chat`      | `deepseek-v4-pro`     |
| `deepseek-reasoner`  | `deepseek-reasoner`   |
| `deepseek-r1`        | `deepseek-reasoner`   |
| `deepseek-coder`     | `deepseek-v4-pro`     |
| `gpt-4o`             | `gpt-4o`              |
| `gpt-4o-mini`        | `gpt-4o-mini`         |
| `o1`                 | `o1`                  |
| `o1-mini`            | `o1-mini`             |
| `o3-mini`            | `o3-mini`             |

不在别名表里的模型名会原样透传给 provider,所以 provider 一发布新模型就能直接用。

## 冒烟测试

启动服务并通过 stdio 发一些原始 JSON-RPC 请求:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | python -m openai_compatible_mcp
```

或用自带的测试客户端:

```bash
PYTHONPATH=src python tests/smoke_test.py
```

## 开发

```bash
# 建虚拟环境
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux

# 可编辑安装
pip install -e ".[dev]"

# 跑测试
PYTHONPATH=src python tests/test_unit.py
PYTHONPATH=src python tests/smoke_test.py
```

## 协议

MIT —— 见 [LICENSE](LICENSE)。
