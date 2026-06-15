#!/usr/bin/env bash
# ====================================================================
# openai-compatible-mcp  -  Codex 翻译代理 启动包装（Linux / macOS）
#
# 用途: 一键启动 Codex → DeepSeek Responses API 翻译代理
#       (默认监听 127.0.0.1:7878,转发到 api.deepseek.com)。
#
# 行为:
#   - 优先调用 `openai-compatible-mcp-proxy`(pip install 时自动加到 PATH)
#   - 端口被占用时打一行提示就退出
#   - Ctrl+C 或关闭终端 = 代理停止
#
# 用法:
#   1) chmod +x proxy-launch.sh && sudo cp proxy-launch.sh /usr/local/bin/proxy-launch
#   2) 直接跑:  proxy-launch
# ====================================================================
set -e

PORT=7878

# ---------- 0. 探测端口 ----------
if (echo >/dev/tcp/127.0.0.1/$PORT) >/dev/null 2>&1; then
    echo "[proxy-launch] $PORT 端口已被占用,代理应该已经在跑(curl http://127.0.0.1:$PORT/v1/models 确认)。"
    exit 0
fi

# ---------- 1. 选命令 ----------
PROXY_CMD=""
if command -v openai-compatible-mcp-proxy >/dev/null 2>&1; then
    PROXY_CMD="openai-compatible-mcp-proxy"
elif command -v openai-compatible-mcp >/dev/null 2>&1; then
    PROXY_CMD="openai-compatible-mcp"
else
    echo "[proxy-launch] 找不到 openai-compatible-mcp / openai-compatible-mcp-proxy 命令。"
    echo "              请先:  pip install openai-compatible-mcp"
    exit 1
fi

# ---------- 2. 启动 ----------
echo "[proxy-launch] 启动 Codex 翻译代理 (127.0.0.1:$PORT -> api.deepseek.com)"
echo "[proxy-launch] Ctrl+C 即可停止代理"
echo
exec "$PROXY_CMD" "$@"
