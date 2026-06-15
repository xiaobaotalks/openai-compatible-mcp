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
@app.route("/", methods=["GET"])
def root():
    """Browser/curl hitting the proxy URL gets a friendly info page instead of 404."""
    return jsonify({
        "name": "openai-compatible-mcp proxy",
        "role": "Codex Responses API  ->  DeepSeek Chat Completions",
        "upstream": DEEPSEEK_API_BASE,
        "api_key_configured": bool(DEEPSEEK_API_KEY),
        "endpoints": {
            "POST /responses": "Codex-style Responses API (preferred)",
            "POST /v1/responses": "Same as above, with /v1 prefix",
            "GET  /v1/models": "List model aliases that proxy knows about",
            "GET  /health": "Liveness probe (returns upstream + key status)",
        },
        "quick_test": "curl http://127.0.0.1:7878/health",
        "codex_config": "~/.codex/config.toml -> base_url = http://127.0.0.1:7878",
    })


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
