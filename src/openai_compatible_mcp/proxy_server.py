"""
Codex Responses API <-> DeepSeek Chat Completions translation proxy.

Translates OpenAI Responses API requests (used by Codex CLI) to
DeepSeek's OpenAI-compatible Chat Completions API, then converts
the response back to the Responses format.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Generator


# ---------------------------------------------------------------------------
# Optional deps auto-install: 让用户只 `pip install openai-compatible-mcp`
# 就能用 `openai-compatible-mcp --proxy`,不用单独装 flask / httpx。
# ---------------------------------------------------------------------------
def _ensure_deps():
    missing = []
    try:
        import flask  # noqa: F401
    except ImportError:
        missing.append("flask")
    try:
        import httpx  # noqa: F401
    except ImportError:
        missing.append("httpx")
    if missing:
        print(f"[proxy] 缺少依赖: {missing}, 正在自动安装...", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing]
        )
        print("[proxy] 依赖安装完成", file=sys.stderr)


_ensure_deps()

import httpx  # noqa: E402
from flask import Flask, Response, jsonify, request, stream_with_context  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# 优先读环境变量,其次是写在用户主目录 ~/.openai-compatible-mcp/proxy.json
# (由 wizard 在用户配 API Key 时写入),最后是默认值。
_CONFIG_DIR = Path.home() / ".openai-compatible-mcp"
_CONFIG_PATH = _CONFIG_DIR / "proxy.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[proxy] WARN 读 {_CONFIG_PATH} 失败: {e}", file=sys.stderr)
    return {}


CONFIG = _load_config()
DEEPSEEK_API_BASE = os.environ.get(
    "DEEPSEEK_API_BASE", CONFIG.get("deepseek_api_base", "https://api.deepseek.com")
)
DEEPSEEK_API_KEY = os.environ.get(
    "DEEPSEEK_API_KEY", CONFIG.get("deepseek_api_key", "")
)
PROXY_HOST = os.environ.get(
    "PROXY_HOST", CONFIG.get("proxy_host", "127.0.0.1")
)
PROXY_PORT = int(
    os.environ.get("PROXY_PORT", str(CONFIG.get("proxy_port", 7878)))
)

# Codex -> DeepSeek model name mapping
MODEL_MAP: dict[str, str] = CONFIG.get("model_map", {
    "deepseek-v4-flash": "deepseek-chat",
    "deepseek-v4-pro": "deepseek-chat",
    "deepseek-v3-flash": "deepseek-chat",
    "deepseek-v3": "deepseek-chat",
    "deepseek-chat": "deepseek-chat",
    "deepseek-reasoner": "deepseek-reasoner",
    "deepseek-coder": "deepseek-chat",
    "deepseek-r1": "deepseek-reasoner",
})
DEFAULT_MODEL = CONFIG.get("default_model", "deepseek-chat")

# Network tunables
UPSTREAM_TIMEOUT = float(CONFIG.get("upstream_timeout", 600))
VERBOSE = bool(CONFIG.get("verbose", False))

_CONFIG_DIR = Path.home() / ".openai-compatible-mcp"
_CONFIG_PATH = _CONFIG_DIR / "proxy.json"

# 模块级可变配置(用户改完 /api/* 后会立即生效,不用重启 proxy)
_CFG_STATE: dict = {
    "deepseek_api_base": os.environ.get(
        "DEEPSEEK_API_BASE", CONFIG.get("deepseek_api_base", "https://api.deepseek.com")
    ),
    "deepseek_api_key": os.environ.get(
        "DEEPSEEK_API_KEY", CONFIG.get("deepseek_api_key", "")
    ),
    "default_model": CONFIG.get("default_model", "deepseek-chat"),
    "model_map": CONFIG.get("model_map", MODEL_MAP),
}


def _persist_config() -> bool:
    """把当前 _CFG_STATE 同步写到 ~/.openai-compatible-mcp/proxy.json。"""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "deepseek_api_base": _CFG_STATE["deepseek_api_base"],
            "deepseek_api_key": _CFG_STATE["deepseek_api_key"],
            "default_model": _CFG_STATE["default_model"],
            "model_map": _CFG_STATE["model_map"],
        }
        with _CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[proxy] WARN 写 {_CONFIG_PATH} 失败: {e}", file=sys.stderr)
        return False


# 兼容外部直接读 DEEPSEEK_API_KEY 的代码(从 _CFG_STATE 实时取)
def _key() -> str:
    env = os.environ.get("DEEPSEEK_API_KEY", "")
    return env if env else _CFG_STATE["deepseek_api_key"]


def _base() -> str:
    env = os.environ.get("DEEPSEEK_API_BASE", "")
    return env if env else _CFG_STATE["deepseek_api_base"]


# 旧名(下面其它逻辑还在用 DEEPSEEK_API_KEY / DEEPSEEK_API_BASE 全局变量)
DEEPSEEK_API_BASE = _CFG_STATE["deepseek_api_base"]
DEEPSEEK_API_KEY = _CFG_STATE["deepseek_api_key"]


def _mask_key(k: str) -> str:
    """给前端展示用的 key 遮罩(只露前 7 + 后 4 位)。"""
    if not k:
        return ""
    if len(k) <= 14:
        return k[:3] + "•" * (len(k) - 6) + k[-3:]
    return k[:7] + "•" * (len(k) - 11) + k[-4:]


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(*args):
    if VERBOSE:
        print("[proxy]", *args, flush=True)


# ---------------------------------------------------------------------------
# Request translation: Responses API -> Chat Completions
# ---------------------------------------------------------------------------
def map_model(model: str) -> str:
    if not model:
        return DEFAULT_MODEL
    if model in MODEL_MAP:
        return MODEL_MAP[model]
    # best-effort fallback
    m = model.lower()
    if "reason" in m or "r1" in m:
        return "deepseek-reasoner"
    return DEFAULT_MODEL


def _content_to_chat(content: Any) -> Any:
    """Convert a Responses API content part(s) to a Chat Completions content value."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype in ("input_text", "text"):
                parts.append({"type": "text", "text": part.get("text", "")})
            elif ptype == "input_image":
                # DeepSeek chat completions doesn't support images.
                # Keep the marker so the model knows an image was sent.
                url = part.get("image_url") or part.get("url") or ""
                if isinstance(url, dict):
                    url = url.get("url", "")
                parts.append({"type": "text", "text": f"[image omitted: {url}]"})
            elif ptype == "refusal":
                parts.append({"type": "text", "text": part.get("refusal", "")})
            else:
                # Unknown part type - stringify it.
                parts.append({"type": "text", "text": json.dumps(part, ensure_ascii=False)})
        if len(parts) == 1 and parts[0]["type"] == "text":
            return parts[0]["text"]
        return parts
    return str(content)


def _input_to_messages(input_data: Any) -> list[dict]:
    """Translate Responses API `input` to Chat Completions `messages`."""
    messages: list[dict] = []
    if input_data is None:
        return messages
    if isinstance(input_data, str):
        messages.append({"role": "user", "content": input_data})
        return messages
    if not isinstance(input_data, list):
        return messages

    for item in input_data:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        role = item.get("role")

        # Function tool result
        if itype == "function_call_output" or role == "tool":
            content = item.get("output")
            if isinstance(content, list):
                content = "\n".join(
                    str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in content
                )
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id") or item.get("id") or "",
                "content": "" if content is None else str(content),
            })
            continue

        # Assistant function call record
        if itype == "function_call" or (role == "assistant" and item.get("function_call")):
            fc = item.get("function_call") or {
                "name": item.get("name"),
                "arguments": item.get("arguments"),
            }
            args = fc.get("arguments") or ""
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            tool_calls = [{
                "id": item.get("call_id") or item.get("id") or ("call_" + uuid.uuid4().hex[:24]),
                "type": "function",
                "function": {
                    "name": fc.get("name", ""),
                    "arguments": args,
                },
            }]
            messages.append({
                "role": "assistant",
                "content": item.get("content") or "",
                "tool_calls": tool_calls,
            })
            continue

        # Regular message
        if role in ("system", "developer", "user", "assistant"):
            msg = {"role": role if role != "developer" else "system", "content": _content_to_chat(item.get("content", ""))}
            if item.get("name"):
                msg["name"] = item["name"]
            messages.append(msg)
            continue

        # Unknown shape - serialize
        messages.append({"role": "user", "content": json.dumps(item, ensure_ascii=False)})
    return messages


def _tools_to_chat(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") in ("function", None) and (t.get("name") or t.get("function")):
            if "function" in t and isinstance(t["function"], dict):
                fn = t["function"]
                out.append({
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    },
                })
            else:
                out.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                })
    return out or None


def build_chat_request(body: dict) -> dict:
    chat_req: dict[str, Any] = {
        "model": map_model(body.get("model")),
        "messages": _input_to_messages(body.get("input")),
        "stream": bool(body.get("stream", False)),
    }

    # Inject system prompt from `instructions`
    instructions = body.get("instructions")
    if instructions:
        chat_req["messages"].insert(0, {"role": "system", "content": instructions})

    # Optional passthrough fields
    for key in (
        "temperature", "top_p", "max_tokens", "max_completion_tokens",
        "frequency_penalty", "presence_penalty", "stop", "seed", "user",
        "logprobs", "top_logprobs", "n", "parallel_tool_calls",
    ):
        if key in body and body[key] is not None:
            chat_req[key] = body[key]

    tools = _tools_to_chat(body.get("tools"))
    if tools:
        chat_req["tools"] = tools
    if "tool_choice" in body and body["tool_choice"] is not None:
        chat_req["tool_choice"] = body["tool_choice"]

    # DeepSeek supports response_format for JSON-style structured output
    if isinstance(body.get("text"), dict):
        fmt = body["text"].get("format")
        if isinstance(fmt, dict) and fmt.get("type") in ("json_object", "json_schema"):
            chat_req["response_format"] = {"type": fmt["type"]}

    return chat_req


# ---------------------------------------------------------------------------
# Response translation: Chat Completions -> Responses API
# ---------------------------------------------------------------------------
def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:24]


def make_response_object(chat_resp: dict, request_body: dict | None = None) -> dict:
    choice = (chat_resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    finish_reason = choice.get("finish_reason")
    usage = chat_resp.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0

    output: list[dict] = []
    text_content = message.get("content") or ""
    if text_content:
        output.append({
            "id": _new_id("msg_"),
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{
                "type": "output_text",
                "text": text_content,
                "annotations": [],
            }],
        })

    for tc in (message.get("tool_calls") or []):
        func = tc.get("function") or {}
        args = func.get("arguments") or ""
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        output.append({
            "id": tc.get("id") or _new_id("fc_"),
            "type": "function_call",
            "status": "completed",
            "name": func.get("name", ""),
            "arguments": args,
            "call_id": tc.get("id") or _new_id("call_"),
        })

    status = "completed" if finish_reason in ("stop", "tool_calls", "length", None) else "incomplete"
    incomplete = None
    if status == "incomplete":
        incomplete = {"reason": finish_reason or "unknown"}

    return {
        "id": _new_id("resp_"),
        "object": "response",
        "created_at": int(chat_resp.get("created") or time.time()),
        "status": status,
        "background": False,
        "error": None,
        "incomplete_details": incomplete,
        "instructions": (request_body or {}).get("instructions"),
        "metadata": {},
        "model": chat_resp.get("model", map_model((request_body or {}).get("model", ""))),
        "output": output,
        "parallel_tool_calls": bool((request_body or {}).get("parallel_tool_calls", True)),
        "temperature": (request_body or {}).get("temperature", 1.0),
        "tool_choice": (request_body or {}).get("tool_choice", "auto"),
        "tools": (request_body or {}).get("tools", []),
        "top_p": (request_body or {}).get("top_p", 1.0),
        "max_output_tokens": (request_body or {}).get("max_output_tokens"),
        "previous_response_id": (request_body or {}).get("previous_response_id"),
        "reasoning": None,
        "truncation": (request_body or {}).get("truncation", "disabled"),
        "usage": {
            "input_tokens": prompt_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": completion_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage.get("total_tokens") or (prompt_tokens + completion_tokens),
        },
        "user": (request_body or {}).get("user"),
        "store": bool((request_body or {}).get("store", True)),
    }


# ---------------------------------------------------------------------------
# Streaming translation: Chat Completions SSE -> Responses API SSE
# ---------------------------------------------------------------------------
def _sse(event: str, data: Any) -> str:
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def translate_sse_stream(lines: Generator[str, None, None], request_body: dict) -> Generator[str, None, None]:
    response_id = _new_id("resp_")
    msg_id = _new_id("msg_")
    model_name = ""
    created = int(time.time())
    full_text = ""
    tool_calls: dict[int, dict] = {}
    finish_reason: str | None = None
    usage_payload: dict | None = None
    seen_text_part = False

    base_response: dict = {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "in_progress",
        "background": False,
        "error": None,
        "incomplete_details": None,
        "instructions": request_body.get("instructions"),
        "metadata": {},
        "model": "",
        "output": [],
        "parallel_tool_calls": bool(request_body.get("parallel_tool_calls", True)),
        "temperature": request_body.get("temperature", 1.0),
        "tool_choice": request_body.get("tool_choice", "auto"),
        "tools": request_body.get("tools", []),
        "top_p": request_body.get("top_p", 1.0),
        "max_output_tokens": request_body.get("max_output_tokens"),
        "previous_response_id": request_body.get("previous_response_id"),
        "reasoning": None,
        "truncation": request_body.get("truncation", "disabled"),
        "usage": None,
        "user": request_body.get("user"),
        "store": bool(request_body.get("store", True)),
    }

    yield _sse("response.created", {"type": "response.created", "response": base_response})
    yield _sse("response.in_progress", {"type": "response.in_progress", "response": base_response})

    message_item: dict = {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "status": "in_progress",
        "content": [],
    }
    yield _sse("response.output_item.added", {
        "type": "response.output_item.added",
        "output_index": 0,
        "item": message_item,
    })

    text_part: dict = {"type": "output_text", "text": "", "annotations": []}
    yield _sse("response.content_part.added", {
        "type": "response.content_part.added",
        "item_id": msg_id,
        "output_index": 0,
        "content_index": 0,
        "part": text_part,
    })
    seen_text_part = True

    for raw in lines:
        if raw is None:
            continue
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if not model_name:
            model_name = chunk.get("model", "")
        if "usage" in chunk and chunk["usage"]:
            usage_payload = chunk["usage"]

        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            if "content" in delta and delta["content"] is not None:
                piece = delta["content"]
                full_text += piece
                yield _sse("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": piece,
                })
            if "reasoning_content" in delta and delta["reasoning_content"]:
                # Surface reasoning as a separate reasoning item so the CLI can render it.
                yield _sse("response.reasoning_summary_text.delta", {
                    "type": "response.reasoning_summary_text.delta",
                    "item_id": msg_id,
                    "output_index": 0,
                    "delta": delta["reasoning_content"],
                })
            if "tool_calls" in delta and delta["tool_calls"]:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx is None:
                        idx = 0
                    buf = tool_calls.setdefault(idx, {
                        "id": tc.get("id") or _new_id("call_"),
                        "name": "",
                        "arguments": "",
                        "started": False,
                        "output_index": len(tool_calls) + 1,
                    })
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    func = tc.get("function") or {}
                    if func.get("name"):
                        buf["name"] += func["name"]
                    if func.get("arguments"):
                        buf["arguments"] += func["arguments"]
                    if not buf["started"]:
                        buf["started"] = True
                        buf["output_index"] = 1 + len([k for k, v in tool_calls.items() if v["started"]])  # placeholder
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr

    # Close out the text part
    if seen_text_part:
        final_text_part = {"type": "output_text", "text": full_text, "annotations": []}
        yield _sse("response.output_text.done", {
            "type": "response.output_text.done",
            "item_id": msg_id,
            "output_index": 0,
            "content_index": 0,
            "text": full_text,
        })
        yield _sse("response.content_part.done", {
            "type": "response.content_part.done",
            "item_id": msg_id,
            "output_index": 0,
            "content_index": 0,
            "part": final_text_part,
        })

    final_message = {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": ([{"type": "output_text", "text": full_text, "annotations": []}] if full_text else []),
    }
    yield _sse("response.output_item.done", {
        "type": "response.output_item.done",
        "output_index": 0,
        "item": final_message,
    })

    # Tool call events
    for i, (idx, tc) in enumerate(sorted(tool_calls.items())):
        args_str = tc["arguments"] or ""
        try:
            parsed = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            parsed = args_str
        arguments = json.dumps(parsed, ensure_ascii=False) if not isinstance(parsed, str) else parsed
        item = {
            "id": tc["id"],
            "type": "function_call",
            "status": "completed",
            "name": tc["name"],
            "arguments": arguments,
            "call_id": tc["id"],
        }
        yield _sse("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": i + 1,
            "item": {**item, "arguments": tc["arguments"] or ""},
        })
        yield _sse("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta",
            "item_id": tc["id"],
            "output_index": i + 1,
            "delta": tc["arguments"] or "",
        })
        yield _sse("response.function_call_arguments.done", {
            "type": "response.function_call_arguments.done",
            "item_id": tc["id"],
            "output_index": i + 1,
            "arguments": arguments,
        })
        yield _sse("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": i + 1,
            "item": item,
        })

    status = "completed" if finish_reason in (None, "stop", "tool_calls", "length") else "incomplete"
    incomplete = None
    if status == "incomplete":
        incomplete = {"reason": finish_reason or "unknown"}

    usage_block = None
    if usage_payload:
        pt = usage_payload.get("prompt_tokens", 0) or 0
        ct = usage_payload.get("completion_tokens", 0) or 0
        usage_block = {
            "input_tokens": pt,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": ct,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage_payload.get("total_tokens") or (pt + ct),
        }

    final_response = {
        **base_response,
        "status": status,
        "incomplete_details": incomplete,
        "model": model_name or map_model(request_body.get("model", "")),
        "output": [final_message] + [
            {
                "id": tc["id"],
                "type": "function_call",
                "status": "completed",
                "name": tc["name"],
                "arguments": (lambda a: (json.dumps(json.loads(a), ensure_ascii=False) if a and a.strip().startswith(("{", "[")) else a))(tc["arguments"] or ""),
                "call_id": tc["id"],
            }
            for _, tc in sorted(tool_calls.items())
        ],
        "usage": usage_block,
    }
    yield _sse("response.completed", {"type": "response.completed", "response": final_response})
    yield _sse("response.done", {"type": "response.done", "response": final_response})


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
_ROOT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>openai-compatible-mcp proxy</title>
<style>
:root {
  --bg-0: #0b0d12; --bg-1: #11141b; --bg-2: #181c25; --bg-3: #20252f;
  --line: #2a3140; --line-2: #3a4356;
  --fg-0: #e6e8ec; --fg-1: #a4aab8; --fg-2: #6b7280;
  --cyan: #5eead4; --violet: #a78bfa; --green: #4ade80; --amber: #fbbf24; --red: #f87171;
  --mono: ui-monospace, "JetBrains Mono", Consolas, "Cascadia Code", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--sans); background: var(--bg-0); color: var(--fg-0);
  min-height: 100vh; padding: 32px 16px; line-height: 1.55;
}
.wrap { max-width: 720px; margin: 0 auto; }
.head {
  background: linear-gradient(135deg, rgba(94,234,212,0.10), rgba(167,139,250,0.10));
  border: 1px solid var(--line); border-radius: 14px; padding: 22px 24px; margin-bottom: 18px;
}
.head h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }
.head .sub { font-family: var(--mono); font-size: 12px; color: var(--fg-1); margin-top: 4px; }
.tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.tag {
  font-family: var(--mono); font-size: 11px; padding: 3px 10px; border-radius: 999px;
  background: var(--bg-2); border: 1px solid var(--line); color: var(--fg-1);
}
.tag.ok { color: var(--green); border-color: rgba(74,222,128,0.4); }
.tag.warn { color: var(--amber); border-color: rgba(251,191,36,0.4); }
.card {
  background: var(--bg-1); border: 1px solid var(--line); border-radius: 12px;
  padding: 18px 20px; margin-bottom: 14px;
}
.card h2 {
  font-size: 13px; font-weight: 600; color: var(--fg-1);
  text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 12px;
}
.row { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
.row:last-child { margin-bottom: 0; }
.row label { font-family: var(--mono); font-size: 12px; color: var(--fg-1); min-width: 88px; }
.row input, .row select {
  flex: 1; background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px;
  padding: 9px 12px; font-family: var(--mono); font-size: 13px; color: var(--fg-0);
  outline: none; transition: border 0.15s;
}
.row input:focus, .row select:focus { border-color: var(--cyan); }
.row .btn { flex: 0 0 auto; }
.masked { font-family: var(--mono); font-size: 12px; color: var(--fg-2); }
button {
  background: var(--bg-3); border: 1px solid var(--line-2); color: var(--fg-0);
  padding: 9px 16px; border-radius: 8px; font-family: var(--sans); font-size: 13px;
  font-weight: 500; cursor: pointer; transition: all 0.15s;
}
button:hover { border-color: var(--cyan); color: var(--cyan); }
button.primary { background: linear-gradient(135deg, var(--cyan), var(--violet)); color: #0b0d12; border-color: transparent; }
button.primary:hover { filter: brightness(1.1); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: var(--bg-2); border: 1px solid var(--line-2); border-radius: 8px;
  padding: 10px 18px; font-size: 13px; opacity: 0; pointer-events: none;
  transition: opacity 0.2s, transform 0.2s;
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(-6px); }
.toast.ok { border-color: var(--green); color: var(--green); }
.toast.err { border-color: var(--red); color: var(--red); }
.foot { text-align: center; color: var(--fg-2); font-size: 12px; margin-top: 24px; }
.foot a { color: var(--cyan); text-decoration: none; }
.kv { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.kv .kv-cell { background: var(--bg-2); padding: 10px 14px; border-radius: 8px; border: 1px solid var(--line); }
.kv .kv-cell .k { font-family: var(--mono); font-size: 11px; color: var(--fg-2); text-transform: uppercase; }
.kv .kv-cell .v { font-family: var(--mono); font-size: 13px; color: var(--fg-0); margin-top: 4px; word-break: break-all; }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>openai-compatible-mcp proxy</h1>
    <div class="sub">Codex Responses API &nbsp;→&nbsp; DeepSeek Chat Completions</div>
    <div class="tags" id="tags">
      <span class="tag" id="tag-key">key: ...</span>
      <span class="tag" id="tag-up">upstream: ...</span>
      <span class="tag" id="tag-model">model: ...</span>
    </div>
  </div>

  <div class="card">
    <h2>当前状态</h2>
    <div class="kv">
      <div class="kv-cell"><div class="k">API Key</div><div class="v" id="kv-key">—</div></div>
      <div class="kv-cell"><div class="k">Upstream</div><div class="v" id="kv-base">—</div></div>
      <div class="kv-cell"><div class="k">默认模型</div><div class="v" id="kv-model">—</div></div>
      <div class="kv-cell"><div class="k">监听地址</div><div class="v" id="kv-listen">—</div></div>
    </div>
  </div>

  <div class="card">
    <h2>更新 API Key</h2>
    <div class="row">
      <label>DeepSeek Key</label>
      <input id="inp-key" type="password" placeholder="sk-..." autocomplete="off" spellcheck="false">
      <button class="btn primary" id="btn-key">保存</button>
    </div>
    <div class="row">
      <label></label>
      <span class="masked" id="hint-key"></span>
    </div>
  </div>

  <div class="card">
    <h2>更新上游 / 模型</h2>
    <div class="row">
      <label>Base URL</label>
      <input id="inp-base" type="text" placeholder="https://api.deepseek.com">
      <button class="btn" id="btn-base">保存</button>
    </div>
    <div class="row">
      <label>默认模型</label>
      <select id="inp-model"></select>
      <button class="btn" id="btn-model">保存</button>
    </div>
  </div>

  <div class="card">
    <h2>测试连接</h2>
    <div class="row">
      <label></label>
      <button id="btn-test" class="primary">向 DeepSeek 发送测试请求</button>
      <span class="masked" id="test-out"></span>
    </div>
  </div>

  <div class="foot">
    openai-compatible-mcp proxy · 端口 __PORT__ &nbsp;
    ·&nbsp; <a href="?json=1">View as JSON</a> &nbsp;
    ·&nbsp; <a href="/v1/models" target="_blank">/v1/models</a> &nbsp;
    ·&nbsp; <a href="/health" target="_blank">/health</a>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
const $ = (id) => document.getElementById(id);
async function api(path, method = "GET", body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}
function toast(msg, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show " + (kind || "");
  setTimeout(() => t.className = "toast", 2400);
}
async function refresh() {
  try {
    const s = await api("/api/settings");
    $("tag-key").textContent = s.api_key_configured ? "key: 已加载" : "key: 缺失";
    $("tag-key").className = "tag " + (s.api_key_configured ? "ok" : "warn");
    $("tag-up").textContent = "upstream: " + s.deepseek_api_base.replace(/^https?:\\/\\//, "");
    $("tag-model").textContent = "model: " + s.default_model;
    $("kv-key").textContent = s.api_key_masked || "(未配置)";
    $("kv-base").textContent = s.deepseek_api_base;
    $("kv-model").textContent = s.default_model;
    $("kv-listen").textContent = s.listen;
    $("inp-base").value = s.deepseek_api_base;
    $("hint-key").textContent = s.api_key_masked ? "已加载:" + s.api_key_masked : "";
    const sel = $("inp-model");
    sel.innerHTML = "";
    for (const m of s.model_options) {
      const o = document.createElement("option");
      o.value = m; o.textContent = m;
      if (m === s.default_model) o.selected = true;
      sel.appendChild(o);
    }
  } catch (e) { toast("加载失败: " + e.message, "err"); }
}
$("btn-key").onclick = async () => {
  const v = $("inp-key").value.trim();
  if (!v) { toast("请先粘贴 Key", "err"); return; }
  try {
    await api("/api/key", "POST", { api_key: v });
    $("inp-key").value = "";
    toast("Key 已保存,proxy 实时生效", "ok");
    refresh();
  } catch (e) { toast(e.message, "err"); }
};
$("btn-base").onclick = async () => {
  const v = $("inp-base").value.trim();
  if (!v) return;
  try {
    await api("/api/base-url", "POST", { base_url: v });
    toast("Base URL 已更新", "ok");
    refresh();
  } catch (e) { toast(e.message, "err"); }
};
$("btn-model").onclick = async () => {
  const v = $("inp-model").value;
  try {
    await api("/api/model", "POST", { model: v });
    toast("默认模型已更新", "ok");
    refresh();
  } catch (e) { toast(e.message, "err"); }
};
$("btn-test").onclick = async () => {
  $("test-out").textContent = "测试中…";
  try {
    const r = await api("/api/test", "POST");
    $("test-out").textContent = r.ok ? "✓ " + r.detail : "✗ " + r.detail;
    toast(r.ok ? "连接成功" : "连接失败", r.ok ? "ok" : "err");
  } catch (e) { $("test-out").textContent = "✗ " + e.message; toast(e.message, "err"); }
};
refresh();
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def root():
    """浏览器: 返回 web UI; ?json=1 / curl: 返回 JSON。"""
    if request.args.get("json") == "1":
        return jsonify({
            "name": "openai-compatible-mcp proxy",
            "role": "Codex Responses API  ->  DeepSeek Chat Completions",
            "upstream": DEEPSEEK_API_BASE,
            "api_key_configured": bool(DEEPSEEK_API_KEY),
            "api_key_masked": _mask_key(DEEPSEEK_API_KEY),
            "default_model": _CFG_STATE["default_model"],
            "listen": f"{PROXY_HOST}:{PROXY_PORT}",
            "endpoints": {
                "POST /responses": "Codex-style Responses API (preferred)",
                "POST /v1/responses": "Same as above, with /v1 prefix",
                "GET  /v1/models": "List model aliases that proxy knows about",
                "GET  /health": "Liveness probe (returns upstream + key status)",
            },
            "ui": "Open http://127.0.0.1:" + str(PROXY_PORT) + "/ in a browser to edit settings.",
        })
    return _ROOT_HTML.replace("__PORT__", str(PROXY_PORT))


@app.route("/api/settings", methods=["GET"])
def api_settings():
    """前端拉取当前状态用。"""
    return jsonify({
        "api_key_configured": bool(_key()),
        "api_key_masked": _mask_key(_key()),
        "deepseek_api_base": _base(),
        "default_model": _CFG_STATE["default_model"],
        "model_options": sorted(set(list(_CFG_STATE["model_map"].keys()) + ["deepseek-chat", "deepseek-reasoner"])),
        "listen": f"{PROXY_HOST}:{PROXY_PORT}",
    })


@app.route("/api/key", methods=["POST"])
def api_key():
    data = request.get_json(silent=True) or {}
    new_key = (data.get("api_key") or "").strip()
    if not new_key:
        return jsonify({"ok": False, "error": "api_key 不能为空"}), 400
    if len(new_key) < 10:
        return jsonify({"ok": False, "error": "api_key 太短,至少 10 个字符"}), 400
    _CFG_STATE["deepseek_api_key"] = new_key
    # 全局变量同步(给下面 /responses 等路由用)
    globals()["DEEPSEEK_API_KEY"] = new_key
    ok = _persist_config()
    return jsonify({"ok": ok, "api_key_masked": _mask_key(new_key), "persisted": ok})


@app.route("/api/base-url", methods=["POST"])
def api_base_url():
    data = request.get_json(silent=True) or {}
    new_base = (data.get("base_url") or "").strip()
    if not (new_base.startswith("http://") or new_base.startswith("https://")):
        return jsonify({"ok": False, "error": "base_url 必须以 http:// 或 https:// 开头"}), 400
    _CFG_STATE["deepseek_api_base"] = new_base
    globals()["DEEPSEEK_API_BASE"] = new_base
    ok = _persist_config()
    return jsonify({"ok": ok, "deepseek_api_base": new_base, "persisted": ok})


@app.route("/api/model", methods=["POST"])
def api_model():
    data = request.get_json(silent=True) or {}
    new_model = (data.get("model") or "").strip()
    if not new_model:
        return jsonify({"ok": False, "error": "model 不能为空"}), 400
    _CFG_STATE["default_model"] = new_model
    ok = _persist_config()
    return jsonify({"ok": ok, "default_model": new_model, "persisted": ok})


@app.route("/api/test", methods=["POST"])
def api_test():
    """向当前 base_url 发一个最小 chat 请求,验证 key 是否可用。"""
    import httpx as _httpx
    try:
        r = _httpx.post(
            _base().rstrip("/") + "/v1/chat/completions",
            headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"},
            json={"model": _CFG_STATE["default_model"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            timeout=15.0,
        )
        if r.status_code == 200:
            return jsonify({"ok": True, "detail": f"HTTP 200 · upstream {_base()}"})
        return jsonify({"ok": False, "detail": f"HTTP {r.status_code} · {r.text[:200]}"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "detail": str(e)[:200]})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "upstream": DEEPSEEK_API_BASE,
        "proxy": "codex-responses -> deepseek-chat-completions",
        "api_key_configured": bool(DEEPSEEK_API_KEY),
    })


@app.route("/v1/models", methods=["GET"])
def list_models():
    seen = set()
    data = []
    for slug in sorted(set(list(MODEL_MAP.keys()) + ["deepseek-chat", "deepseek-reasoner"])):
        if slug in seen:
            continue
        seen.add(slug)
        data.append({
            "id": slug,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "deepseek",
        })
    return jsonify({"object": "list", "data": data})


def _upstream_headers(req) -> dict:
    api_key = DEEPSEEK_API_KEY or req.headers.get("Authorization", "").replace("Bearer ", "").strip()
    return {
        "Authorization": f"Bearer {api_key}" if api_key else "",
        "Content-Type": "application/json",
        "Accept": "application/json" if False else "*/*",
    }


def _proxy_request():
    if not DEEPSEEK_API_KEY:
        return jsonify({
            "error": {
                "message": "DEEPSEEK_API_KEY is not configured. Edit proxy/config.json.",
                "type": "configuration_error",
                "code": "missing_api_key",
            }
        }), 500

    try:
        body = request.get_json(force=True, silent=False) or {}
    except Exception as e:
        return jsonify({"error": {"message": f"Invalid JSON: {e}", "type": "invalid_request_error"}}), 400

    chat_req = build_chat_request(body)
    log("chat_req.model =", chat_req["model"], "stream =", chat_req["stream"], "messages =", len(chat_req["messages"]))
    headers = _upstream_headers(request)

    if chat_req["stream"]:
        client = httpx.Client(timeout=UPSTREAM_TIMEOUT)

        def generate():
            with client.stream(
                "POST",
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                json=chat_req,
                headers=headers,
            ) as r:
                if r.status_code >= 400:
                    err_text = r.read().decode("utf-8", errors="ignore")
                    err_obj = {
                        "error": {
                            "message": err_text or r.reason_phrase,
                            "type": "upstream_error",
                            "code": str(r.status_code),
                        }
                    }
                    yield _sse("error", err_obj)
                    return
                # Pass through the upstream lines, translating to Responses SSE.
                yield from translate_sse_stream(r.iter_lines(), body)

        resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    # Non-streaming
    try:
        with httpx.Client(timeout=UPSTREAM_TIMEOUT) as client:
            r = client.post(
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                json=chat_req,
                headers=headers,
            )
    except httpx.HTTPError as e:
        return jsonify({
            "error": {"message": f"Upstream connection error: {e}", "type": "upstream_error"}
        }), 502

    if r.status_code >= 400:
        try:
            err_body = r.json()
        except Exception:
            err_body = {"message": r.text}
        return jsonify({
            "error": {
                "message": err_body.get("error", {}).get("message") if isinstance(err_body.get("error"), dict) else err_body.get("message", r.text),
                "type": "upstream_error",
                "code": str(r.status_code),
            }
        }), r.status_code

    chat_resp = r.json()
    return jsonify(make_response_object(chat_resp, body))


@app.route("/responses", methods=["POST"])
@app.route("/v1/responses", methods=["POST"])
def responses_post():
    return _proxy_request()


@app.errorhandler(404)
def not_found(_e):
    return jsonify({
        "error": {
            "message": f"Unknown route: {request.path}. Try /responses, /v1/responses, /v1/models, or /health.",
            "type": "not_found",
        }
    }), 404


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    if not DEEPSEEK_API_KEY:
        print(
            f"WARNING: DEEPSEEK_API_KEY not set. Wizard should have written it to {_CONFIG_PATH}, "
            f"or set the env var before running.",
            file=sys.stderr,
        )
        print(
            f"  → 三种修复方式(任选其一):",
            file=sys.stderr,
        )
        print(
            f"    1) 重新跑 `openai-compatible-mcp`(无参数),打开浏览器,在向导里填 Key 后点「保存」,再跑 --proxy。",
            file=sys.stderr,
        )
        print(
            f"    2) 临时传入:`openai-compatible-mcp --proxy --api-key sk-你的key`",
            file=sys.stderr,
        )
        print(
            f"    3) 设环境变量:`$env:DEEPSEEK_API_KEY='sk-你的key'`(PowerShell)再跑 --proxy。",
            file=sys.stderr,
        )
    print(f"Proxy listening on http://{PROXY_HOST}:{PROXY_PORT}", flush=True)
    print(f"Forwarding to {DEEPSEEK_API_BASE}/v1/chat/completions", flush=True)
    print("Endpoints: POST /responses  (or /v1/responses), GET /v1/models, GET /health", flush=True)
    app.run(host=PROXY_HOST, port=PROXY_PORT, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
