"""OpenAI-compatible chat client (stdlib only)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Defaults - DeepSeek is the default provider, but anything OpenAI-compatible
# works (OpenAI, Azure OpenAI, Together, Groq, OpenRouter, local llama.cpp, etc.)
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT = 120.0

# Friendly aliases so callers can ask for "deepseek-v4-flash" or "r1" without
# needing to know the provider's exact model name.
MODEL_ALIASES: dict[str, str] = {
    # DeepSeek
    "deepseek-v4-pro": "deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-chat": "deepseek-v4-pro",
    "deepseek-v3": "deepseek-v4-pro",
    "deepseek-reasoner": "deepseek-reasoner",
    "deepseek-r1": "deepseek-reasoner",
    "deepseek-coder": "deepseek-v4-pro",
    # OpenAI
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "o1": "o1",
    "o1-mini": "o1-mini",
    "o3-mini": "o3-mini",
}

# Env vars (any of these work; the first one set wins)
_API_KEY_ENV = (
    "OPENAI_COMPATIBLE_MCP_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)
_BASE_URL_ENV = (
    "OPENAI_COMPATIBLE_MCP_BASE_URL",
    "DEEPSEEK_API_BASE",
    "OPENAI_BASE_URL",
)
_DEFAULT_MODEL_ENV = (
    "OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL",
    "DEEPSEEK_DEFAULT_MODEL",
)
_INCLUDE_REASONING_ENV = "OPENAI_COMPATIBLE_MCP_INCLUDE_REASONING"


def _first_env(names: Iterable[str]) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def get_config() -> dict[str, Any]:
    """Read runtime configuration from the environment."""
    api_key = _first_env(_API_KEY_ENV) or ""
    base_url = _first_env(_BASE_URL_ENV) or DEFAULT_BASE_URL
    default_model = _first_env(_DEFAULT_MODEL_ENV) or DEFAULT_MODEL
    return {
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "default_model": default_model,
        "include_reasoning": os.environ.get(_INCLUDE_REASONING_ENV, "").lower() in ("1", "true", "yes"),
    }


def resolve_model(name: str | None) -> str:
    """Map a friendly alias to a real model name, falling back to default."""
    if not name:
        return get_config()["default_model"]
    return MODEL_ALIASES.get(name, name)


class ChatError(RuntimeError):
    """Raised when the upstream chat API returns an error or is unreachable."""


def _http_post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
            message = (
                err_body.get("error", {}).get("message")
                if isinstance(err_body.get("error"), dict)
                else err_body.get("message")
            ) or e.reason
        except Exception:
            message = e.reason
        raise ChatError(f"upstream {e.code}: {message}") from e
    except urllib.error.URLError as e:
        raise ChatError(f"upstream connection error: {e.reason}") from e
    except TimeoutError as e:
        raise ChatError(f"upstream timeout after {timeout}s") from e


def chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    stop: str | list[str] | None = None,
    system: str | None = None,
    include_reasoning: bool | None = None,
    extra: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send a chat completion request and return the parsed response.

    Returns the full upstream response (OpenAI Chat Completions shape).
    """
    cfg = get_config()
    if not cfg["api_key"]:
        raise ChatError(
            "No API key configured. Set one of: "
            + ", ".join(_API_KEY_ENV)
            + " (e.g. export DEEPSEEK_API_KEY=sk-...)"
        )

    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    body: dict[str, Any] = {
        "model": resolve_model(model or cfg["default_model"]),
        "messages": msgs,
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)
    if top_p is not None:
        body["top_p"] = float(top_p)
    if stop is not None:
        body["stop"] = stop
    if extra:
        body.update(extra)

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    want_reasoning = (
        include_reasoning
        if include_reasoning is not None
        else cfg["include_reasoning"]
    )
    if want_reasoning:
        # Some providers honor this; harmless if ignored.
        body.setdefault("reasoning_effort", "medium")

    data = _http_post_json(
        f"{cfg['base_url']}/v1/chat/completions",
        body,
        headers,
        timeout or DEFAULT_TIMEOUT,
    )
    return data


def extract_content(data: dict) -> str:
    """Pull the assistant text from an OpenAI-shape response."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content") or ""


def extract_reasoning(data: dict) -> str:
    """Pull the reasoning content (DeepSeek-R1 style) if present."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message", {}) or {}
    return msg.get("reasoning_content") or ""


def list_models() -> dict[str, Any]:
    """Return the alias table and the resolved default model."""
    cfg = get_config()
    return {
        "default_model": cfg["default_model"],
        "aliases": dict(sorted(MODEL_ALIASES.items())),
        "base_url": cfg["base_url"],
    }
