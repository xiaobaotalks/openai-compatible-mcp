"""End-to-end smoke test for the MCP server.

Boots the server as a subprocess, speaks JSON-RPC over its stdio, and calls
each tool. Requires DEEPSEEK_API_KEY (or another provider key) in the env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def frame(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_frame(stream) -> dict:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise EOFError("server closed the connection")
        line = line.strip()
        if not line:
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode("ascii").strip().lower()] = v.decode("ascii").strip()
    length = int(headers["content-length"])
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            raise EOFError("server closed mid-message")
        body += chunk
    return json.loads(body.decode("utf-8"))


def call(proc: subprocess.Popen, msg_id: int, method: str, params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
    proc.stdin.write(frame(payload))
    proc.stdin.flush()
    return read_frame(proc.stdout)


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "openai_compatible_mcp", "-v"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    try:
        # 1) initialize
        init = call(proc, 1, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0"},
        })
        print("[init]", json.dumps(init, ensure_ascii=False, indent=2))
        assert init.get("result", {}).get("serverInfo", {}).get("name") == "openai-compatible-mcp"

        # 2) notifications/initialized (no response expected)
        proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        # 3) tools/list
        tools = call(proc, 2, "tools/list")
        names = sorted(t["name"] for t in tools["result"]["tools"])
        print("[tools/list]", names)
        assert names == ["chat", "list_models"]

        # 4) list_models tool
        lm = call(proc, 3, "tools/call", {"name": "list_models", "arguments": {}})
        text = lm["result"]["content"][0]["text"]
        print("[list_models]\n" + text)
        assert "deepseek-v4-pro" in text

        # 5) chat tool
        chat_resp = call(proc, 4, "tools/call", {
            "name": "chat",
            "arguments": {
                "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
                "model": "deepseek-v4-flash",
                "temperature": 0.5,
                "max_tokens": 100,
            },
        })
        if chat_resp.get("result", {}).get("isError"):
            print("[chat FAILED]", chat_resp)
            return 1
        content = chat_resp["result"]["content"]
        print("\n[chat reply]")
        for part in content:
            print(part["text"])
        joined = "".join(p["text"] for p in content)
        assert joined.strip(), "empty response"

        print("\nALL TESTS PASSED")
        return 0
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr = proc.stderr.read().decode("utf-8", errors="ignore")
        if stderr.strip():
            print("\n--- server stderr ---")
            print(stderr)


if __name__ == "__main__":
    sys.exit(main())
