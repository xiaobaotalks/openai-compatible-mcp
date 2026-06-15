"""Entry point: `python -m openai_compatible_mcp`.

新增辅助能力：
  *  `python -m openai_compatible_mcp --install-config`
       自动检测当前 Python 路径 / 操作系统，生成对应 MCP 客户端（Claude Desktop /
       Claude Code / Cursor）可用的配置文件，写入正确位置。
  *  `python -m openai_compatible_mcp --check`
       对本地环境做一次自检，把问题和建议打印到 stderr，便于排错。
  *  `python -m openai_compatible_mcp -v` （原 stdio MCP 服务模式，不变）
       启动时会先做一次自检并把结果写入 stderr（不污染 stdio 协议流）。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .client import ChatError, chat, extract_content, extract_reasoning, get_config, list_models
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
                "Model name or alias (e.g. `deepseek-v4-pro`, `deepseek-v4-flash`, "
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


# ---------------------------------------------------------------------------
# 环境自检 & 自动配置
# ---------------------------------------------------------------------------

def _python_exe() -> str:
    """返回当前解释器的真实可执行文件路径（优先 sys.executable）。"""
    exe = sys.executable
    if exe and Path(exe).is_file():
        return str(Path(exe).resolve())
    fallback = shutil.which("python") or shutil.which("python3") or "python"
    return fallback


def _selfcheck() -> dict:
    """对当前环境做一次自检，返回结构化结果（在 stderr 打印人类可读摘要）。"""
    cfg = get_config()
    exe = _python_exe()

    checks = {
        "python_path": exe,
        "python_version": platform.python_version(),
        "os": f"{platform.system()} ({platform.release()})",
        "module_loadable": False,
        "api_key_set": bool(cfg["api_key"]),
        "base_url": cfg["base_url"],
        "default_model": cfg["default_model"],
    }

    try:
        import openai_compatible_mcp  # noqa: F401
        checks["module_loadable"] = True
    except Exception:
        pass

    problems: list[str] = []
    fixes: list[str] = []

    if not checks["module_loadable"]:
        problems.append("当前 Python 解释器找不到 openai_compatible_mcp 模块")
        fixes.append(
            f"请用该解释器重新安装： "
            f"\"{exe}\" -m pip install -e <项目路径>"
        )

    if not checks["api_key_set"]:
        problems.append("未检测到 API Key 环境变量")
        fixes.append(
            "设置任意一个环境变量："
            "OPENAI_COMPATIBLE_MCP_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY"
        )

    checks["_problems"] = problems
    checks["_fixes"] = fixes
    return checks


def _print_selfcheck(log_fn: Callable[[str], None]) -> dict:
    info = _selfcheck()
    log_fn(f"Python: {info['python_path']} ({info['python_version']})")
    log_fn(f"OS: {info['os']}")
    log_fn(f"Base URL: {info['base_url']}  |  Default model: {info['default_model']}")
    log_fn(f"API key configured: {'YES' if info['api_key_set'] else 'NO'}")
    for p in info["_problems"]:
        log_fn(f"[问题] {p}")
    for f in info["_fixes"]:
        log_fn(f"[建议] {f}")
    return info


# -- 各客户端的配置文件路径 -----------------------------------------------

def _mcp_config_paths() -> list[tuple[str, Path]]:
    """返回 [(客户端名, 配置文件路径)] 的列表。Windows / macOS / Linux 都覆盖。"""
    system = platform.system().lower()
    home = Path.home()

    paths: list[tuple[str, Path]] = []

    if system.startswith("win") or system == "windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        paths += [
            ("claude_desktop", appdata / "Claude" / "claude_desktop_config.json"),
            ("claude_code",   home / ".claude" / "settings.json"),
            ("cursor",        home / ".cursor" / "mcp.json"),
        ]
    elif system == "darwin":
        paths += [
            ("claude_desktop", home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"),
            ("claude_code",   home / ".claude" / "settings.json"),
            ("cursor",        home / ".cursor" / "mcp.json"),
        ]
    else:  # Linux / others
        config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        paths += [
            ("claude_desktop", config / "Claude" / "claude_desktop_config.json"),
            ("claude_code",   home / ".claude" / "settings.json"),
            ("cursor",        home / ".cursor" / "mcp.json"),
        ]
    return paths


def _claude_code_extra_paths() -> dict[str, Path]:
    """返回 Claude Code 额外需要的文件路径（跳过登录引导的 .claude.json 等）。"""
    home = Path.home()
    return {
        "onboarding": home / ".claude.json",
        "settings": home / ".claude" / "settings.json",
    }


def _write_claude_code_native_config(api_key: str, python_exe: str, dry_run: bool, log_fn: Callable[[str], None]) -> bool:
    """直接写入 Claude Code 原生配置（跳过登录 + 走 DeepSeek，不依赖环境变量）。

    1. ~/.claude.json -> {"hasCompletedOnboarding": true} （跳过官方登录引导）
    2. ~/.claude/settings.json -> env + model + mcpServers （走 DeepSeek + 启用本 MCP 工具）
    """
    paths = _claude_code_extra_paths()

    onboarding = {"hasCompletedOnboarding": True}
    settings: dict[str, Any] = {
        "env": {
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_SMALL_FAST_MODEL": "deepseek-v4-pro",
            "CLAUDE_CODE_EFFORT_LEVEL": "max",
        },
        "model": "deepseek-v4-pro",
        "skipIntroduction": True,
        "skipWelcome": True,
    }
    # 额外挂入我们的 MCP 工具，让 Claude Code 对话中也能调用 chat / list_models
    servers = settings.get("mcpServers") or {}
    if isinstance(servers, dict):
        servers["openai-compatible"] = _make_mcp_entry(python_exe, api_key)
    settings["mcpServers"] = servers

    any_written = False
    for name, payload in (("onboarding", onboarding), ("settings", settings)):
        path = paths[name]
        if dry_run:
            log_fn(f"[claude_code/{name}] (dry-run) 会写入: {path}")
            log_fn(json.dumps(payload, indent=2, ensure_ascii=False))
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            log_fn(f"[claude_code/{name}] 已写入: {path}")
            any_written = True
        except PermissionError as e:
            log_fn(f"[claude_code/{name}] 权限不足 - {path}: {e}")
        except Exception as e:
            log_fn(f"[claude_code/{name}] 写入失败 - {path}: {e}")
    return any_written


def _make_mcp_entry(python_exe: str, api_key: str | None) -> dict:
    """生成一个标准 MCP 服务器定义块（可直接粘到 settings.json 的 mcpServers 里）。"""
    entry: dict[str, Any] = {
        "command": python_exe,
        "args": ["-m", "openai_compatible_mcp"],
    }
    if api_key:
        entry["env"] = {"DEEPSEEK_API_KEY": api_key}
    return entry


def _merge_mcp_config(existing: dict, python_exe: str, api_key: str | None) -> dict:
    """把 openai-compatible 服务器合并进已有的 mcpServers 配置，不破坏其他条目。"""
    merged = dict(existing or {})
    servers = dict(merged.get("mcpServers", {}) or {})
    servers["openai-compatible"] = _make_mcp_entry(python_exe, api_key)
    merged["mcpServers"] = servers
    return merged


def _install_config(target_client: str | None, api_key: str | None, dry_run: bool, log_fn: Callable[[str], None]) -> int:
    python_exe = _python_exe()

    cfg_key_from_env = get_config()["api_key"]
    effective_key = api_key or cfg_key_from_env
    if not effective_key:
        log_fn("[警告] 当前没有可用的 API Key。配置文件仍会生成，但 chat 工具暂时无法调用。")
        log_fn("       之后可在生成的配置文件里手动填入 env.DEEPSEEK_API_KEY。")

    log_fn(f"使用 Python: {python_exe}")

    # 处理各客户端的 MCP 配置（mcpServers 字段）
    targets = _mcp_config_paths()
    if target_client:
        targets = [(name, path) for name, path in targets if name == target_client]

    log_fn(f"MCP 注册到: " + ", ".join(name for name, _ in targets))

    any_written = False
    for name, path in targets:
        existing: dict = {}
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception as e:
                log_fn(f"[{name}] 跳过 - 无法读取 {path}: {e}")
                continue

        new_cfg = _merge_mcp_config(existing, python_exe, effective_key)

        if dry_run:
            log_fn(f"[{name}] (dry-run) 会写入: {path}")
            log_fn(json.dumps(new_cfg, indent=2, ensure_ascii=False))
            continue

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            log_fn(f"[{name}] 已写入: {path}")
            any_written = True
        except PermissionError as e:
            log_fn(f"[{name}] 权限不足 - {path}: {e}")
        except Exception as e:
            log_fn(f"[{name}] 写入失败 - {path}: {e}")

    # 对 Claude Code 额外写入原生配置（跳过登录引导 + 走 DeepSeek 网关，不需要用户再手工建 JSON）
    if target_client is None or target_client == "claude_code":
        log_fn("")
        log_fn("→ 额外处理 Claude Code: 写入原生配置（跳过登录 + 接入 DeepSeek）")
        ok = _write_claude_code_native_config(effective_key or "", python_exe, dry_run, log_fn)
        if ok:
            any_written = True

    log_fn("")
    if dry_run:
        log_fn("dry-run 完成。去掉 --dry-run 后再次执行即可真正写入。")
    elif any_written:
        log_fn("完成！请重启你的 MCP 客户端（Claude Desktop / Claude Code / Cursor）使其加载新配置。")
        log_fn("Claude Code: 在终端输入 claude 启动，不要再点登录按钮。")
    else:
        log_fn("没有任何配置被写入，请检查上方日志。")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="只做一次环境自检并输出到 stderr，不启动 MCP 服务器。",
    )
    mode.add_argument(
        "--wizard",
        action="store_true",
        help=(
            "启动图形化配置向导(浏览器自动打开 http://127.0.0.1:8989)。"
            "用于配置 Claude Code / Codex / Cursor 等客户端。"
        ),
    )
    mode.add_argument(
        "--install-config",
        action="store_true",
        help=(
            "自动检测当前 Python 路径并生成/更新 MCP 客户端的配置文件 "
            "(Claude Desktop / Claude Code / Cursor)。"
        ),
    )
    parser.add_argument(
        "--client",
        choices=["claude_desktop", "claude_code", "cursor"],
        default=None,
        help="只针对某个客户端写入 / 展示配置（配合 --install-config 使用）。",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="指定写入配置文件 env.DEEPSEEK_API_KEY 的值（配合 --install-config 使用）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的内容，不真正改文件（配合 --install-config 使用）。",
    )

    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(f"[openai-compatible-mcp] {msg}", file=sys.stderr, flush=True)

    if args.check:
        _print_selfcheck(log)
        return 0

    if args.wizard:
        # 把 wizard.py 作为子进程跑,避免污染本进程的 stdio(MCP 协议流)。
        import subprocess as _sp
        wizard_py = Path(__file__).resolve().parent / "wizard.py"
        log(f"启动配置向导: {wizard_py}")
        try:
            rc = _sp.call([sys.executable, str(wizard_py)])
        except KeyboardInterrupt:
            rc = 0
        return rc

    if args.install_config:
        return _install_config(
            target_client=args.client,
            api_key=args.api_key,
            dry_run=args.dry_run,
            log_fn=log,
        )

    if args.proxy:
        from openai_compatible_mcp import proxy_server
        try:
            proxy_server.main()
        except KeyboardInterrupt:
            pass
        return 0

    # 智能默认: 没传任何子命令, 并且 stdin 是 TTY, 并且没有 API key 环境变量
    # → 自动启动 wizard(避免用户在 PowerShell 傻等 MCP server 卡住)。
    has_key = bool(os.environ.get("OPENAI_COMPATIBLE_MCP_API_KEY")
                   or os.environ.get("DEEPSEEK_API_KEY")
                   or os.environ.get("OPENAI_API_KEY"))
    if sys.stdin.isatty() and not has_key and not args.verbose:
        log("未检测到 API key 环境变量,且未指定子命令。")
        log("将自动启动配置向导(127.0.0.1:8989);如要直接启动 MCP server 请设置 API key 或加 -v。")
        import subprocess as _sp
        wizard_py = Path(__file__).resolve().parent / "wizard.py"
        try:
            rc = _sp.call([sys.executable, str(wizard_py)])
        except KeyboardInterrupt:
            rc = 0
        return rc

    # 默认进入 MCP 服务器模式；启动前做一次自检到 stderr，方便排错
    _print_selfcheck(log)

    server = build_server(verbose=args.verbose)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
