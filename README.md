# openai-compatible-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that
bridges to any **OpenAI-compatible chat API** — DeepSeek, OpenAI, Azure OpenAI,
OpenRouter, Together, Groq, local llama.cpp, and friends.

> **Default provider:** DeepSeek. Switch to any OpenAI-compatible endpoint with
> a single environment variable.
> **Version:** [v0.2.21](https://pypi.org/project/openai-compatible-mcp/0.2.21/)
> — see [CHANGELOG.md](CHANGELOG.md) for recent fixes.

The package ships **two ways to integrate** with MCP-aware clients:

| Mode                | When to use                                                   | Status                |
| ------------------- | ------------------------------------------------------------- | --------------------- |
| **MCP server**      | Client launches `python -m openai_compatible_mcp` as a child   | ✅ Stable, stdio      |
| **Direct API**      | Client calls your already-running `openai-compatible-mcp` proxy at `http://127.0.0.1:7878/v1` | ✅ v0.2.21+, recommended for Codex CLI |

The **wizard** at <http://127.0.0.1:8989> auto-detects which mode your client
needs and writes the right config.

---

## Quick start (Codex CLI / Claude / Cursor)

### 1. Install + start the wizard

```bash
pip install --upgrade openai-compatible-mcp
python -m openai_compatible_mcp
```

A browser opens at <http://127.0.0.1:8989>.

### 2. Pick provider, paste API key, click "Apply"

The wizard writes the right config for:

- **Codex CLI** → `~/.codex/config.toml` (using *direct API mode*, no MCP sub-process)
- **Claude Desktop** → `claude_desktop_config.json`
- **Cursor** → `~/.cursor/mcp.json`
- **Claude Code** → `~/.claude.json`

…and does **not** overwrite any other servers you've configured.

### 3. Restart Codex / Claude

```bash
codex        # or restart Claude Desktop / Cursor
```

That's it.

> **Heads up — Codex 0.140+:** the wizard uses provider id `openai_compatible`
> (not `openai_compatible_mcp`) because codex reserves the `openai` prefix for
> built-ins. If you have an older config from a pre-v0.2.21 wizard, the next
> "Apply" will auto-migrate it.

---

## Integration modes

### A. Direct API (recommended for Codex CLI 0.140+)

Wizard writes this into `~/.codex/config.toml`:

```toml
# written by openai-compatible-mcp v0.2.21 (utf-8, no BOM)
model = "deepseek-v4-pro"
model_provider = "openai_compatible"

[projects.'c:\users\you']
trust_level = "trusted"

[windows]
sandbox = "elevated"

[model_providers.openai_compatible]
name = "OpenAI Compatible"
base_url = "http://127.0.0.1:7878/v1"
api_key = "sk-..."
```

Codex talks straight to the local proxy at `http://127.0.0.1:7878/v1`. **No MCP
sub-process, no 30-second startup timeout.**

### B. MCP server (for Claude Desktop, Cursor, etc.)

Wizard writes a `[mcp_servers.X]` block in your client config that launches
`python -m openai_compatible_mcp` as a stdio child. The MCP server then opens
its own HTTP listener for chat-completion calls.

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

## Architecture

```
┌──────────────────┐       stdio JSON-RPC        ┌─────────────────────┐
│ Claude Desktop   │ ───────────────────────────▶│                     │
│ Cursor / VSCode  │                             │ openai-compatible-  │
│ Claude Code      │                             │ mcp                 │
└──────────────────┘                             │                     │
                                                 │   ┌─────────────┐   │
┌──────────────────┐      HTTP /v1/chat/...      │   │ Proxy       │   │
│ Codex CLI 0.140+ │ ───────────────────────────▶│   │ 127.0.0.1   │   │
│ (direct API)     │                             │   │   :7878     │   │
└──────────────────┘                             │   └──────┬──────┘   │
                                                 │          │          │
┌──────────────────┐      http://127.0.0.1:8989  │          ▼          │
│ Your browser     │ ───────────────────────────▶│   Upstream API      │
│ (wizard UI)      │     one-time setup          │   (DeepSeek etc.)   │
└──────────────────┘                             └─────────────────────┘
```

- **`python -m openai_compatible_mcp`** starts **both** the wizard (port 8989) and
  the local proxy (port 7878) in the same process.
- The wizard is for setup only — close it after writing config.
- The proxy is a long-running OpenAI-compatible endpoint — leave it running or
  set up auto-start (the wizard offers this).

---

## CLI install (no wizard)

```bash
git clone https://github.com/xiaobaotalks/openai-compatible-mcp.git
cd openai-compatible-mcp
pip install -e .

# Set your key
export DEEPSEEK_API_KEY="sk-..."   # or OPENAI_COMPATIBLE_MCP_API_KEY

# Smoke test
PYTHONPATH=src python tests/smoke_test.py
```

### Environment variables

| Setting       | Variables tried (in order)                                                       |
| ------------- | -------------------------------------------------------------------------------- |
| API key       | `OPENAI_COMPATIBLE_MCP_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`          |
| Base URL      | `OPENAI_COMPATIBLE_MCP_BASE_URL` → `DEEPSEEK_API_BASE` → `OPENAI_BASE_URL`      |
| Default model | `OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL` → `DEEPSEEK_DEFAULT_MODEL`                 |

---

## Features

- Zero third-party dependencies (Python 3.9+ stdlib only)
- Works with **any** OpenAI-compatible chat API
- Built-in wizard: 1 browser tab → 1 click → all clients configured
- **Dual mode**: MCP stdio *and* direct HTTP `/v1/chat/completions`
- Friendly model aliases (`deepseek-v4-flash` → `deepseek-v4-flash`, `r1` → `deepseek-reasoner`)
- Optional reasoning content extraction (DeepSeek-R1 style)
- Tiny: ~2,000 lines of code

---

## Tools (MCP mode)

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

**Example**:

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

### `list_models`

Returns the default model and the alias table.

---

## Built-in model aliases

| Alias               | Resolves to          |
| ------------------- | -------------------- |
| `deepseek-v4-pro`   | `deepseek-v4-pro`    |
| `deepseek-v4-flash` | `deepseek-v4-flash`  |
| `deepseek-v3`       | `deepseek-v4-pro`    |
| `deepseek-chat`     | `deepseek-v4-pro`    |
| `deepseek-reasoner` | `deepseek-reasoner`  |
| `deepseek-r1`       | `deepseek-reasoner`  |
| `gpt-4o`            | `gpt-4o`             |
| `gpt-4o-mini`       | `gpt-4o-mini`        |
| `o1`                | `o1`                 |
| `o1-mini`           | `o1-mini`            |
| `o3-mini`           | `o3-mini`            |

Any name not in the table is passed through unchanged.

---

## Recent fixes (v0.2.13 → v0.2.21)

The wizard has gone through several bug fixes in the past week. If you have
an **older** version, upgrading and re-applying the wizard is the fastest way
out of most "Codex says invalid TOML" or "wizard won't start" problems.

| Version | Fix                                                                          |
| ------- | ---------------------------------------------------------------------------- |
| 0.2.13  | Initial Codex support (writes `~/.codex/config.toml`)                        |
| 0.2.14  | `wire_api = "responses"` (Codex 0.140+ deprecates `"chat"`)                  |
| 0.2.15  | Strip child sections (e.g. `[mcp_servers.X.env]`) to avoid duplicate keys    |
| 0.2.16  | Strip UTF-8 BOM (PowerShell `Set-Content -Encoding UTF8` adds one)           |
| 0.2.17  | Add `written by openai-compatible-mcp vX.Y.Z` marker + 3-layer BOM defense   |
| 0.2.18  | Strip **all** Unicode invisible chars (ZWSP, ZWNBSP, LRM, …) — line 2 of user's config had a ZWNBSP that broke TOML |
| 0.2.19  | Add `import re` (typo in v0.2.18 broke wizard on startup) + port fallback    |
| 0.2.20  | Robust relative import (top-level script mode)                               |
| 0.2.21  | **Rename provider `openai_compatible_mcp` → `openai_compatible` (Codex reserved `openai` prefix) + stop writing `[mcp_servers.X]` by default + new `_strip_any_section` to clear any leftover blocks** |

See [CHANGELOG.md](CHANGELOG.md) for the full history.

---

## Development

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux
pip install -e ".[dev]"
PYTHONPATH=src python tests/smoke_test.py
```

## License

MIT — see [LICENSE](LICENSE).
