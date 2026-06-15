"""Minimal MCP stdio server (JSON-RPC 2.0 over Content-Length framed stdin/stdout).

Implements just enough of the Model Context Protocol spec to expose tools to
MCP clients (Claude Desktop, Cursor, Claude Code, etc.).

No third-party dependencies - uses only the Python standard library.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "openai-compatible-mcp"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# stdio transport (Content-Length framing per JSON-RPC over stdio)
# ---------------------------------------------------------------------------
def _send(payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def _read() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode("ascii").strip().lower()] = v.decode("ascii").strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = b""
    while len(body) < length:
        chunk = sys.stdin.buffer.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class Tool:
    def __init__(self, name: str, description: str, input_schema: dict, handler: Callable[[dict], list]):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPServer:
    def __init__(self, name: str = SERVER_NAME, version: str = SERVER_VERSION):
        self.name = name
        self.version = version
        self._tools: dict[str, Tool] = {}
        self._log: Callable[[str], None] = lambda msg: None

    def set_logger(self, fn: Callable[[str], None]) -> None:
        self._log = fn

    def add_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    # -- request handling ----------------------------------------------------
    def _handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "notifications/initialized":
            return None  # notification, no response

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": [t.to_spec() for t in self._tools.values()]},
            }

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            tool = self._tools.get(name)
            if tool is None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            try:
                result = tool.handler(arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                }
            except Exception as e:
                self._log(f"tool {name} error: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not implemented: {method}"},
        }

    def run(self) -> None:
        """Block, reading JSON-RPC messages from stdin until EOF."""
        self._log(f"{self.name} v{self.version} listening on stdio")
        self._log(
            "提示: "
            "如果在 Claude Desktop / Claude Code / Cursor 中 '未连接服务器', "
            "请先执行 `python -m openai_compatible_mcp --install-config` "
            "自动生成配置文件，然后重启客户端。"
        )
        while True:
            try:
                msg = _read()
            except (json.JSONDecodeError, ValueError) as e:
                self._log(f"malformed request: {e}")
                continue
            if msg is None:
                break
            response = self._handle(msg)
            if response is not None:
                _send(response)
        self._log("connection closed")
