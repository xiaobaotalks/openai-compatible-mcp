"""Entry point: `python -m openai_compatible_mcp`."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .client import ChatError, chat, extract_content, extract_reasoning, list_models
from .server import MCPServer, Tool

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------
def tool_chat(arguments: dict) -> list:
    messages = arguments.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("`messages` must be a non-empty array of {role, content} objects")

    data = chat(
        messages=messages,
        model=arguments.get("model"),
        temperature=arguments.get("temperature"),
        max_tokens=arguments.get("max_tokens"),
        top_p=arguments.get("top_p"),
        stop=arguments.get("stop"),
        system=arguments.get("system"),
        include_reasoning=arguments.get("include_reasoning"),
    )
    content = extract_content(data)
    reasoning = extract_reasoning(data)
    usage = data.get("usage") or {}

    parts: list[dict] = []
    if reasoning:
        parts.append({
            "type": "text",
            "text": f"<think>\n{reasoning}\n</think>\n",
        })
    parts.append({
        "type": "text",
        "text": content,
    })
    usage_line = (
        f"\n\n---\nmodel: {data.get('model', '?')} | "
        f"prompt_tokens: {usage.get('prompt_tokens', '?')} | "
        f"completion_tokens: {usage.get('completion_tokens', '?')} | "
        f"total_tokens: {usage.get('total_tokens', '?')}"
    )
    parts.append({"type": "text", "text": usage_line})

    return {"content": parts, "isError": False}


def tool_list_models(_arguments: dict) -> list:
    info = list_models()
    body = (
        f"Default model: {info['default_model']}\n"
        f"Base URL:      {info['base_url']}\n\n"
        f"Aliases:\n" + "\n".join(f"  {k}  ->  {v}" for k, v in info["aliases"].items())
    )
    return {"content": [{"type": "text", "text": body}], "isError": False}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "description": (
                "Conversation history. Each item is an object with `role` "
                "(`system`|`user`|`assistant`) and `content` (string)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["system", "user", "assistant"]},
                    "content": {"type": "string"},
                },
                "required": ["role", "content"],
            },
        },
        "model": {
            "type": "string",
            "description": (
                "Model name or alias (e.g. `deepseek-chat`, `deepseek-v4-flash`, "
                "`deepseek-r1`, `gpt-4o-mini`). Defaults to the configured default model."
            ),
        },
        "temperature": {
            "type": "number",
            "description": "Sampling temperature, 0-2. Lower = more deterministic.",
        },
        "max_tokens": {
            "type": "integer",
            "description": "Maximum tokens to generate.",
        },
        "top_p": {"type": "number", "description": "Nucleus sampling cutoff."},
        "stop": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "Stop sequences.",
        },
        "system": {
            "type": "string",
            "description": "System prompt, prepended to the conversation.",
        },
        "include_reasoning": {
            "type": "boolean",
            "description": (
                "If true and the model returns reasoning content (e.g. DeepSeek-R1), "
                "include it in the response wrapped in <think>...</think>."
            ),
        },
    },
    "required": ["messages"],
}

LIST_MODELS_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_server(verbose: bool = False) -> MCPServer:
    def log(msg: str) -> None:
        if verbose:
            print(f"[openai-compatible-mcp] {msg}", file=sys.stderr, flush=True)

    server = MCPServer()
    server.set_logger(log)
    server.add_tool(Tool(
        name="chat",
        description=(
            "Send a chat completion request to a configured OpenAI-compatible API "
            "(DeepSeek by default) and return the assistant's reply. Use this whenever "
            "you need a single-shot LLM response inside a tool call."
        ),
        input_schema=CHAT_SCHEMA,
        handler=tool_chat,
    ))
    server.add_tool(Tool(
        name="list_models",
        description="List the configured default model and friendly model aliases.",
        input_schema=LIST_MODELS_SCHEMA,
        handler=tool_list_models,
    ))
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openai-compatible-mcp",
        description="MCP server that bridges to OpenAI-compatible chat APIs (default: DeepSeek).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Log diagnostics to stderr (does not interfere with the stdio MCP transport).",
    )
    args = parser.parse_args(argv)

    server = build_server(verbose=args.verbose)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
