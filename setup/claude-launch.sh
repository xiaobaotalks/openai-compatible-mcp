#!/usr/bin/env bash
# openai-compatible-mcp  -  Claude Code 启动包装（macOS / Linux）
#
# 在调用真正的 `claude` 命令前,先把 DeepSeek 网关 + API Key
# 注入到当前进程的环境变量里,确保 Claude Code 不走官方登录。

set -e

# 1) 找 claude
CLAUDE_EXE="$(command -v claude 2>/dev/null || true)"
if [ -z "$CLAUDE_EXE" ]; then
    for cand in \
        "$HOME/.npm-global/bin/claude" \
        "$HOME/.local/bin/claude" \
        "/usr/local/bin/claude" \
        "/opt/homebrew/bin/claude"
    do
        if [ -x "$cand" ]; then CLAUDE_EXE="$cand"; break; fi
    done
fi
if [ -z "$CLAUDE_EXE" ]; then
    echo "[错误] 找不到 claude 命令。请先运行:  npm install -g @anthropic-ai/claude-code" >&2
    exit 1
fi

# 2) 读 API Key
API_KEY="${DEEPSEEK_API_KEY:-${OPENAI_COMPATIBLE_MCP_API_KEY:-}}"
if [ -z "$API_KEY" ] && [ -f "$HOME/.claude/settings.json" ]; then
    API_KEY="$(grep -o '"ANTHROPIC_AUTH_TOKEN"[[:space:]]*:[[:space:]]*"[^"]*"' "$HOME/.claude/settings.json" | head -1 | sed -E 's/.*"([^"]*)"/\1/')"
fi
if [ -z "$API_KEY" ]; then
    echo "[警告] 没找到 DeepSeek API Key,Claude Code 仍会走官方网关。" >&2
fi

# 3) 注入 env
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="$API_KEY"
export ANTHROPIC_API_KEY=""
export ANTHROPIC_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-pro"
export ANTHROPIC_SMALL_FAST_MODEL="deepseek-v4-pro"
export CLAUDE_CODE_EFFORT_LEVEL="max"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export DISABLE_TELEMETRY=1

echo "[claude-launch] 走 DeepSeek 网关: $ANTHROPIC_BASE_URL"
echo "[claude-launch] 启动 claude: $CLAUDE_EXE"
exec "$CLAUDE_EXE" "$@"
