# openai-compatible-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that
bridges to any **OpenAI-compatible chat API** — DeepSeek, OpenAI, Azure OpenAI,
OpenRouter, Together, Groq, local llama.cpp, and friends.

> **Default provider:** DeepSeek. Switch to any OpenAI-compatible endpoint with
> a single environment variable.

The server runs over **stdio** (the standard MCP transport) and exposes two
tools that any MCP-compatible client can call:

- **`chat`** — send a chat completion, get the assistant's reply
- **`list_models`** — show the configured default model and friendly aliases

## Features

- Zero third-party dependencies (Python 3.9+ stdlib only)
- Works with **any** OpenAI-compatible chat API
- Friendly model aliases (`deepseek-v4-flash` → `deepseek-chat`, `r1` → `deepseek-reasoner`, etc.)
- Optional reasoning content extraction (DeepSeek-R1 style)
- Built-in JSON-RPC 2.0 over stdio MCP transport
- Tiny: ~400 lines of code

## Quick start

### 1. Install

From source:

```bash
git clone https://github.com/xiaobaotalks/openai-compatible-mcp.git
cd openai-compatible-mcp
pip install -e .
```

Or run directly without installing:

```bash
PYTHONPATH=src python -m openai_compatible_mcp
```

### 2. Configure

Set your API key and (optionally) the base URL:

```bash
# DeepSeek (default)
export DEEPSEEK_API_KEY="sk-..."

# OpenAI
export OPENAI_API_KEY="sk-..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://api.openai.com"

# Azure OpenAI
export OPENAI_COMPATIBLE_MCP_API_KEY="..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT"

# Local llama.cpp server
export OPENAI_COMPATIBLE_MCP_BASE_URL="http://127.0.0.1:8080"
export OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL="llama-3.1-8b"

# Custom: anything speaking the OpenAI /v1/chat/completions protocol
export OPENAI_COMPATIBLE_MCP_API_KEY="..."
export OPENAI_COMPATIBLE_MCP_BASE_URL="https://my.example.com"
export OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL="my-model"
```

Environment variable lookup order (first one set wins):

| Setting       | Variables tried (in order)                                                       |
| ------------- | -------------------------------------------------------------------------------- |
| API key       | `OPENAI_COMPATIBLE_MCP_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`          |
| Base URL      | `OPENAI_COMPATIBLE_MCP_BASE_URL` → `DEEPSEEK_API_BASE` → `OPENAI_BASE_URL`      |
| Default model | `OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL` → `DEEPSEEK_DEFAULT_MODEL`                 |

### 3. Wire it up to an MCP client

#### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

See `examples/claude_desktop_config.json` for a full sample.

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

#### Claude Code / other stdio clients

Same shape: launch `python -m openai_compatible_mcp` as a subprocess and
read/write JSON-RPC over its stdin/stdout.

## Tools

### `chat`

Send a chat completion to the configured provider.

| Field              | Type            | Required | Description                                                |
| ------------------ | --------------- | -------- | ---------------------------------------------------------- |
| `messages`         | array           | yes      | List of `{role, content}` messages (oldest first).         |
| `model`            | string          | no       | Model name or alias (e.g. `deepseek-v4-flash`, `o1-mini`). |
| `temperature`      | number          | no       | 0-2, lower = more deterministic.                           |
| `max_tokens`       | integer         | no       | Maximum tokens to generate.                                |
| `top_p`            | number          | no       | Nucleus sampling cutoff.                                   |
| `stop`             | string \| array | no       | Stop sequence(s).                                          |
| `system`           | string          | no       | System prompt (prepended to the conversation).             |
| `include_reasoning`| boolean         | no       | Wrap reasoning content in `<think>...</think>`.            |

**Example** (from an MCP client):

```json
{
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "messages": [
        {"role": "user", "content": "Write a haiku about Python."}
      ],
      "model": "deepseek-v4-flash",
      "temperature": 0.7
    }
  }
}
```

The tool returns text content with the assistant's reply plus a usage
footer:

```
Whitespace glides through the code,
Indents bloom like spring leaves—
Bugs hide, then they are gone.

---
model: deepseek-chat | prompt_tokens: 12 | completion_tokens: 28 | total_tokens: 40
```

### `list_models`

Returns the default model and the alias table.

## Built-in model aliases

You can edit `src/openai_compatible_mcp/client.py` to add or remove aliases
for your provider. Defaults:

| Alias               | Resolves to          |
| ------------------- | -------------------- |
| `deepseek-v4-flash` | `deepseek-chat`      |
| `deepseek-v4-pro`   | `deepseek-chat`      |
| `deepseek-v3`       | `deepseek-chat`      |
| `deepseek-chat`     | `deepseek-chat`      |
| `deepseek-reasoner` | `deepseek-reasoner`  |
| `deepseek-r1`       | `deepseek-reasoner`  |
| `deepseek-coder`    | `deepseek-chat`      |
| `gpt-4o`            | `gpt-4o`             |
| `gpt-4o-mini`       | `gpt-4o-mini`        |
| `o1`                | `o1`                 |
| `o1-mini`           | `o1-mini`            |
| `o3-mini`           | `o3-mini`            |

Any model name not in the alias table is passed through to the provider
unchanged, so the latest models work the moment a provider releases them.

## Smoke test

Run the server and send a few raw JSON-RPC requests over stdio:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | python -m openai_compatible_mcp
```

Or use the included test client:

```bash
PYTHONPATH=src python tests/smoke_test.py
```

## Development

```bash
# Create a venv
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux

# Editable install
pip install -e ".[dev]"

# Run tests
PYTHONPATH=src python tests/smoke_test.py
```

## License

MIT — see [LICENSE](LICENSE).
