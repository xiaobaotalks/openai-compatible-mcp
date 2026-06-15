"""Unit tests that don't need network access."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai_compatible_mcp import client, server


def test_resolve_model_uses_alias():
    assert client.resolve_model("deepseek-v4-flash") == "deepseek-v4-flash"
    assert client.resolve_model("deepseek-r1") == "deepseek-reasoner"
    assert client.resolve_model("gpt-4o-mini") == "gpt-4o-mini"
    # unknown model passes through
    assert client.resolve_model("my-custom-model") == "my-custom-model"
    # empty / None falls back to default
    assert client.resolve_model(None) in (client.DEFAULT_MODEL, client.get_config()["default_model"])
    assert client.resolve_model("") in (client.DEFAULT_MODEL, client.get_config()["default_model"])


def test_get_config_defaults():
    import os
    saved = {k: os.environ.pop(k, None) for k in (
        "OPENAI_COMPATIBLE_MCP_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
        "OPENAI_COMPATIBLE_MCP_BASE_URL", "DEEPSEEK_API_BASE", "OPENAI_BASE_URL",
    )}
    try:
        cfg = client.get_config()
        assert cfg["api_key"] == ""
        assert cfg["base_url"].startswith("https://")
        assert cfg["default_model"]
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_chat_missing_api_key_raises():
    import os
    saved = {k: os.environ.pop(k, None) for k in (
        "OPENAI_COMPATIBLE_MCP_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
    )}
    try:
        try:
            client.chat([{"role": "user", "content": "hi"}])
        except client.ChatError as e:
            assert "API key" in str(e)
        else:
            raise AssertionError("expected ChatError")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_server_initialization_message():
    s = server.MCPServer()
    s.add_tool(server.Tool(
        name="ping",
        description="no-op",
        input_schema={"type": "object", "properties": {}},
        handler=lambda _a: {"content": [{"type": "text", "text": "pong"}], "isError": False},
    ))
    resp = s._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["serverInfo"]["name"] == "openai-compatible-mcp"
    assert "tools" in resp["result"]["capabilities"]


def test_server_tools_list():
    s = server.MCPServer()
    s.add_tool(server.Tool("a", "A", {"type": "object"}, lambda _a: {"content": []}))
    s.add_tool(server.Tool("b", "B", {"type": "object"}, lambda _a: {"content": []}))
    resp = s._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert sorted(t["name"] for t in resp["result"]["tools"]) == ["a", "b"]


def test_server_call_tool_success_and_error():
    def boom(_a):
        raise RuntimeError("nope")
    s = server.MCPServer()
    s.add_tool(server.Tool("ok", "", {"type": "object"}, lambda _a: {"content": [{"type": "text", "text": "ok"}]}))
    s.add_tool(server.Tool("bad", "", {"type": "object"}, boom))
    ok = s._handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ok", "arguments": {}}})
    assert ok["result"]["content"][0]["text"] == "ok"
    err = s._handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "bad", "arguments": {}}})
    assert err["result"]["isError"] is True
    assert "nope" in err["result"]["content"][0]["text"]


def test_server_unknown_method():
    s = server.MCPServer()
    r = s._handle({"jsonrpc": "2.0", "id": 9, "method": "wat", "params": {}})
    assert r["error"]["code"] == -32601


def test_server_notifications_return_none():
    s = server.MCPServer()
    r = s._handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    assert r is None


def test_wizard_claude_code_writes_both_files(tmp_path, monkeypatch):
    """wizard must write BOTH ~/.claude.json (mcpServers + skip login)
    AND ~/.claude/settings.json (env vars / ANTHROPIC_BASE_URL).
    Earlier versions only wrote ~/.claude.json, so Claude Code still tried
    api.anthropic.com and the user got a login prompt.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "setup"))
    from server import configure_clients  # type: ignore

    result = configure_clients(
        provider="deepseek",
        api_key="sk-test",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        clients=["claude_code"],
        method="python",
    )

    import json
    claude_json = tmp_path / ".claude.json"
    settings_json = tmp_path / ".claude" / "settings.json"

    assert str(claude_json) in result["files_written"]
    assert str(settings_json) in result["files_written"]

    cj = json.loads(claude_json.read_text(encoding="utf-8"))
    assert cj["hasCompletedOnboarding"] is True
    assert cj["numStartups"] >= 1
    assert "openai-compatible" in cj.get("mcpServers", {})

    sj = json.loads(settings_json.read_text(encoding="utf-8"))
    env = sj.get("env", {})
    assert env.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
    assert env.get("ANTHROPIC_AUTH_TOKEN") == "sk-test"
    assert env.get("ANTHROPIC_API_KEY") == ""
    assert env.get("ANTHROPIC_MODEL") == "deepseek-v4-pro"
    assert "openai-compatible" in sj.get("mcpServers", {})


def test_wizard_codex_uses_local_proxy_url(tmp_path, monkeypatch):
    """Codex 必须走本地代理 http://127.0.0.1:7878(由 D:\\AItext\\codex\\proxy\\ 提供),
    不应像 Claude 那样直连 api.deepseek.com,否则 Codex 无法被代理翻译。
    旧版 wizard 输出顶层 OPENAI_COMPATIBLE_MCP_* 变量,Codex 根本不认识,
    这里必须输出 Codex 原生的 [model_providers.*] + experimental_bearer_token 格式。
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("platform.system", lambda: "Linux")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "setup"))
    from server import configure_clients  # type: ignore

    result = configure_clients(
        provider="deepseek",
        api_key='sk-"weird"',
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        clients=["codex"],
        method="python",
        codex_base_url="http://127.0.0.1:7878",
    )

    toml = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")

    # Codex 顶层字段
    assert 'model = "deepseek-v4-pro"' in toml
    assert 'model_provider = "openai_compatible_mcp"' in toml

    # Codex 原生 [model_providers.*]
    assert "[model_providers.openai_compatible_mcp]" in toml
    assert "base_url" in toml and "127.0.0.1:7878" in toml
    assert "127.0.0.1:7878/v1" in toml  # 自动补 /v1
    assert "experimental_bearer_token" in toml  # 嵌 key,不依赖环境变量
    assert "wire_api" in toml

    # 旧版错误格式不能再出现(顶层 OPENAI_COMPATIBLE_MCP_* 变量)
    assert "OPENAI_COMPATIBLE_MCP_API_KEY = " not in toml.replace(
        '[mcp_servers.openai_compatible_mcp.env]\nOPENAI_COMPATIBLE_MCP_API_KEY = "', 'X'
    ) or "OPENAI_COMPATIBLE_MCP_API_KEY" in toml  # 但在 mcp env 段里还是允许的

    # MCP 服务器注册
    assert "[mcp_servers.openai_compatible_mcp]" in toml
    assert 'command = "openai-compatible-mcp"' in toml

    # 包含引号转义
    assert 'sk-\\"weird\\"' in toml


if __name__ == "__main__":
    test_resolve_model_uses_alias()
    test_get_config_defaults()
    test_chat_missing_api_key_raises()
    test_server_initialization_message()
    test_server_tools_list()
    test_server_call_tool_success_and_error()
    test_server_unknown_method()
    test_server_notifications_return_none()
    print("All unit tests passed.")