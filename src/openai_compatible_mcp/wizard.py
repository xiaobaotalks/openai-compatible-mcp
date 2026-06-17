"""
openai-compatible-mcp setup wizard - local server.

Run via install.bat / install.sh, or directly:
    python -m openai_compatible_mcp_setup
    python server.py

Starts a tiny HTTP server on http://127.0.0.1:8989 that serves index.html
and provides a JSON API for the wizard. Opens the browser automatically.

Pure stdlib so it runs on any Python 3.9+ without installing anything.
"""
from __future__ import annotations

import http.server
import json
import os
import platform
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

HOST = "127.0.0.1"
PORT = 8989
PACKAGE_NAME = "openai-compatible-mcp"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"

# 在 PyPI 装的包里,wizard.py 跟 wizard_index.html 在同一目录 (site-packages/.../wizard_index.html)
# 在开发仓库里,也可能走 setup/index.html(兼容老 setup/server.py)。
_WIZARD_DIR = Path(__file__).resolve().parent
WIZARD_DIR = _WIZARD_DIR  # 兼容老 setup/ 目录里用 WIZARD_DIR 的代码
_BUNDLED_HTML = _WIZARD_DIR / "wizard_index.html"
_DEV_HTML = _WIZARD_DIR.parent.parent.parent / "setup" / "index.html"
INDEX_HTML = _BUNDLED_HTML if _BUNDLED_HTML.exists() else _DEV_HTML

# Defaults
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
        "env_key": "DEEPSEEK_API_KEY",
        "key_prefix": "sk-",
        "key_help": "Get one at https://platform.deepseek.com/api_keys",
    },
    "openai": {
        "name": "OpenAI",
        "default_base_url": "https://api.openai.com",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "key_help": "Get one at https://platform.openai.com/api-keys",
    },
    "azure": {
        "name": "Azure OpenAI",
        "default_base_url": "",  # user must provide
        "default_model": "gpt-4o",
        "env_key": "OPENAI_COMPATIBLE_MCP_API_KEY",
        "key_prefix": "",
        "key_help": "Paste your Azure endpoint in 'Base URL' (e.g. https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT)",
    },
    "openrouter": {
        "name": "OpenRouter",
        "default_base_url": "https://openrouter.ai/api",
        "default_model": "openai/gpt-4o-mini",
        "env_key": "OPENAI_COMPATIBLE_MCP_API_KEY",
        "key_prefix": "sk-or-",
        "key_help": "Get one at https://openrouter.ai/keys",
    },
    "groq": {
        "name": "Groq",
        "default_base_url": "https://api.groq.com/openai",
        "default_model": "llama-3.1-8b-instant",
        "env_key": "OPENAI_COMPATIBLE_MCP_API_KEY",
        "key_prefix": "gsk_",
        "key_help": "Get one at https://console.groq.com/keys",
    },
    "custom": {
        "name": "Custom OpenAI-compatible endpoint",
        "default_base_url": "",
        "default_model": "",
        "env_key": "OPENAI_COMPATIBLE_MCP_API_KEY",
        "key_prefix": "",
        "key_help": "Any service that exposes /v1/chat/completions",
    },
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def info(msg: str) -> None:
    """Print to stderr (visible if running in foreground)."""
    print(f"[wizard] {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], timeout: int = 60, **kw) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, **kw
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def python_exe() -> str:
    """Best Python to use: prefer the one running this script."""
    return sys.executable


def detect_env() -> dict:
    """Gather environment info for the wizard."""
    py = python_exe()
    py_version = platform.python_version()
    pip_version = "?"
    pkg_version = None
    pkg_path = None

    # pip version
    rc, out, _ = run([py, "-m", "pip", "--version"], timeout=10)
    if rc == 0:
        # "pip 25.0.1 from C:\... (python 3.12)"
        parts = out.split()
        if len(parts) >= 2:
            pip_version = parts[1]

    # package version
    rc, out, _ = run([py, "-c", f"import importlib.metadata as m; print(m.version('{PACKAGE_NAME}'))"], timeout=10)
    if rc == 0:
        pkg_version = out.strip()

    # find package path (for showing user where it lives)
    rc, out, _ = run(
        [py, "-c", f"import {PACKAGE_NAME.replace('-', '_')}; print({PACKAGE_NAME.replace('-', '_')}.__file__)"],
        timeout=10,
    )
    if rc == 0:
        pkg_path = out.strip()

    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python": py,
        "python_version": py_version,
        "pip_version": pip_version,
        "package_installed": pkg_version is not None,
        "package_version": pkg_version,
        "package_path": pkg_path,
    }


def install_package() -> dict:
    """Run pip install."""
    py = python_exe()
    info(f"installing {PACKAGE_NAME} ...")
    rc, out, err = run(
        [py, "-m", "pip", "install", "--upgrade", PACKAGE_NAME],
        timeout=180,
    )
    if rc != 0:
        return {"ok": False, "stdout": out, "stderr": err}
    return {"ok": True, "stdout": out, "stderr": err}


def test_connection(provider: str, api_key: str, base_url: str, model: str) -> dict:
    """Try a single chat completion to verify config."""
    py = python_exe()
    snippet = f"""
import json, os
os.environ['OPENAI_COMPATIBLE_MCP_API_KEY'] = {api_key!r}
os.environ['OPENAI_COMPATIBLE_MCP_BASE_URL'] = {base_url!r}
os.environ['OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL'] = {model!r}
from openai_compatible_mcp.client import chat
try:
    r = chat([{{"role": "user", "content": "ping" if False else "ping (reply with one word: ok)"}}], model={model!r}, max_tokens=20)
    print("OK")
    print(repr(r)[:300])
except Exception as e:
    print("ERROR:", type(e).__name__, str(e)[:500])
"""
    rc, out, err = run([py, "-c", snippet], timeout=60)
    return {"ok": rc == 0 and "OK" in out, "stdout": out, "stderr": err}


# --------------------------------------------------------------------------- #
# Config file writers
# --------------------------------------------------------------------------- #


def _claude_desktop_config_path() -> Path:
    sysname = platform.system()
    if sysname == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    # Linux
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "Claude" / "claude_desktop_config.json"


def _cursor_config_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _claude_code_mcp_path() -> Path:
    """Claude Code reads mcpServers + onboarding state from ~/.claude.json."""
    return Path.home() / ".claude.json"


def _claude_code_env_path() -> Path:
    """Claude Code reads env vars (ANTHROPIC_BASE_URL etc.) from ~/.claude/settings.json."""
    return Path.home() / ".claude" / "settings.json"


def _codex_config_path() -> Path:
    """Codex 0.140+ 读的是 ~/.codex/config.toml(跨平台),不再用 %APPDATA%\\codex\\。"""
    return Path.home() / ".codex" / "config.toml"


def _strip_toml_section(text: str, header: str) -> str:
    """从 TOML 文本中移除 [header] 段(到下一个 [section] 或 EOF)。"""
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            if in_section:
                in_section = False
            if stripped == header:
                in_section = True
                continue
        if not in_section:
            out.append(line)
    return "\n".join(out)


def _merge_codex_config(
    existing: str,
    model: str,
    provider_key: str,
    provider_block: str,
    mcp_block: str,
) -> str:
    """合并 model / model_provider / 我们的两个段,保留其它段。"""
    import re

    text = existing

    text, n_model = re.subn(
        r'^[ \t]*model[ \t]*=.*$',
        f'model = "{model}"',
        text,
        flags=re.MULTILINE,
    )
    if n_model == 0:
        text = f'model = "{model}"\n' + text

    text, n_mp = re.subn(
        r'^[ \t]*model_provider[ \t]*=.*$',
        f'model_provider = "{provider_key}"',
        text,
        flags=re.MULTILINE,
    )
    if n_mp == 0:
        text = re.sub(
            r'^(model = "[^"]*"\n)',
            r'\1model_provider = "' + provider_key + '"\n',
            text,
            count=1,
            flags=re.MULTILINE,
        )

    text = _strip_toml_section(text, f"[model_providers.{provider_key}]")
    text = _strip_toml_section(text, f"[mcp_servers.{provider_key}]")

    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + provider_block.rstrip() + "\n\n" + mcp_block.rstrip() + "\n"
    return text


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _merge_mcp_servers(existing: dict, server_name: str, server_cfg: dict) -> dict:
    """Merge a new MCP server into an existing config without clobbering others."""
    data = dict(existing) if existing else {}
    servers = dict(data.get("mcpServers", {}))
    servers[server_name] = server_cfg
    data["mcpServers"] = servers
    return data


def configure_clients(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    clients: list[str],
    method: str = "uvx",  # "uvx" | "pipx" | "module" | "python"
    codex_base_url: str = "",  # 单独给 Codex 用（本地代理 127.0.0.1:7878）
) -> dict:
    """Write config files for the requested MCP clients.

    method controls how the MCP server is launched:
      - uvx:    uvx openai-compatible-mcp      (requires `uv`)
      - pipx:   pipx run openai-compatible-mcp  (requires `pipx`)
      - module: python -m openai_compatible_mcp (no extra tool)
      - python: /abs/path/to/python -m openai_compatible_mcp
    """
    prov = PROVIDERS.get(provider, PROVIDERS["custom"])
    env_key = prov["env_key"]

    # Build the server config
    env = {env_key: api_key}
    if base_url:
        env["OPENAI_COMPATIBLE_MCP_BASE_URL"] = base_url
    if model:
        env["OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL"] = model

    if method == "uvx":
        command, args = "uvx", ["openai-compatible-mcp"]
    elif method == "pipx":
        command, args = "pipx", ["run", "openai-compatible-mcp"]
    elif method == "python":
        command, args = python_exe(), ["-m", "openai_compatible_mcp"]
    else:  # module
        command, args = "python", ["-m", "openai_compatible_mcp"]

    server_cfg = {"command": command, "args": args, "env": env}
    written: list[str] = []

    if "claude_desktop" in clients:
        p = _claude_desktop_config_path()
        existing = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
        merged = _merge_mcp_servers(existing, "openai-compatible", server_cfg)
        _atomic_write_json(p, merged)
        written.append(str(p))

    if "cursor" in clients:
        p = _cursor_config_path()
        existing = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
        merged = _merge_mcp_servers(existing, "openai-compatible", server_cfg)
        _atomic_write_json(p, merged)
        written.append(str(p))

    if "claude_code" in clients:
        # 1) ~/.claude.json -> mcpServers + 跳过登录引导
        mcp_path = _claude_code_mcp_path()
        existing = {}
        if mcp_path.exists():
            try:
                existing = json.loads(mcp_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
        merged_mcp = _merge_mcp_servers(existing, "openai-compatible", server_cfg)
        merged_mcp["hasCompletedOnboarding"] = True
        merged_mcp["numStartups"] = 99
        _atomic_write_json(mcp_path, merged_mcp)
        written.append(str(mcp_path))

        # 2) ~/.claude/settings.json -> env 字段（ANTHROPIC_BASE_URL / AUTH_TOKEN / 模型别名等）
        env_path = _claude_code_env_path()
        existing_env = {}
        if env_path.exists():
            try:
                existing_env = json.loads(env_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing_env = {}
        env_cfg = dict(existing_env or {})
        env_block = dict(env_cfg.get("env", {}) or {})
        env_block.update({
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": model or "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model or "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model or "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model or "deepseek-v4-pro",
            "ANTHROPIC_SMALL_FAST_MODEL": model or "deepseek-v4-pro",
            "CLAUDE_CODE_EFFORT_LEVEL": "max",
        })
        env_cfg["env"] = env_block
        env_cfg["model"] = model or "deepseek-v4-pro"
        env_cfg["skipIntroduction"] = True
        env_cfg["skipWelcome"] = True
        # 把 mcpServers 也写一份到 settings.json（部分版本会优先读这里）
        mcp_in_env = _merge_mcp_servers(
            {"mcpServers": env_cfg.get("mcpServers", {}) or {}},
            "openai-compatible",
            server_cfg,
        )
        env_cfg["mcpServers"] = mcp_in_env["mcpServers"]
        _atomic_write_json(env_path, env_cfg)
        written.append(str(env_path))

    if "codex" in clients:
        p = _codex_config_path()
        existing_text = ""
        if p.exists():
            existing_text = p.read_text(encoding="utf-8")
        # Codex 默认走本地代理 127.0.0.1:7878(走 D:\AItext\codex\proxy\ 下的 Flask 代理
        # 把 Codex 格式翻译成 DeepSeek 格式);若用户没填,fallback 到主 base_url。
        codex_url = (codex_base_url or "http://127.0.0.1:7878").rstrip("/")
        provider_block, mcp_block = _build_codex_blocks(codex_url, model, env_key, api_key)
        merged = _merge_codex_config(
            existing_text,
            model=model,
            provider_key="openai_compatible_mcp",
            provider_block=provider_block,
            mcp_block=mcp_block,
        )
        _atomic_write_text(p, merged)
        written.append(str(p))

        # 同时写一份 proxy 配置到 ~/.openai-compatible-mcp/proxy.json,
        # 这样用户跑 `openai-compatible-mcp --proxy` 就能直接拿到 key。
        try:
            proxy_dir = Path.home() / ".openai-compatible-mcp"
            proxy_dir.mkdir(parents=True, exist_ok=True)
            proxy_cfg = {
                "deepseek_api_key": api_key,
                "deepseek_api_base": base_url or "https://api.deepseek.com",
                "proxy_host": "127.0.0.1",
                "proxy_port": 7878,
                "default_model": model or "deepseek-v4-pro",
                "model_map": {
                    "deepseek-v4-pro": "deepseek-chat",
                    "deepseek-v4-flash": "deepseek-chat",
                    "deepseek-v3-flash": "deepseek-chat",
                    "deepseek-v3": "deepseek-chat",
                    "deepseek-chat": "deepseek-chat",
                    "deepseek-reasoner": "deepseek-reasoner",
                    "deepseek-coder": "deepseek-chat",
                    "deepseek-r1": "deepseek-reasoner",
                },
            }
            (proxy_dir / "proxy.json").write_text(
                json.dumps(proxy_cfg, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written.append(str(proxy_dir / "proxy.json"))
        except Exception as e:  # noqa: BLE001
            # proxy.json 写不进不该让 wizard 整体失败
            print(f"[wizard] WARN 写 proxy.json 失败: {e}", file=sys.stderr)

    return {"ok": True, "files_written": written, "server_cfg": server_cfg}


def _build_codex_toml(base_url: str, model: str, env_key: str, api_key: str) -> str:
    """兼容旧调用:直接返回完整片段(不推荐,会被 _build_codex_blocks + merge 替代)。"""
    provider, mcp = _build_codex_blocks(base_url, model, env_key, api_key)
    return f'model = "{model}"\nmodel_provider = "openai_compatible_mcp"\n\n{provider}\n\n{mcp}\n'


def _build_codex_blocks(base_url: str, model: str, env_key: str, api_key: str) -> tuple[str, str]:
    """返回 (provider_block, mcp_block) 两个独立 TOML 段。"""
    base = base_url.rstrip("/") or "https://api.deepseek.com"
    if not base.endswith("/v1"):
        base = base + "/v1"
    provider_key = "openai_compatible_mcp"
    safe_key = api_key.replace("\\", "\\\\").replace('"', '\\"')
    provider_block = (
        f"[model_providers.{provider_key}]\n"
        f'name = "OpenAI Compatible"\n'
        f'base_url = "{base}"\n'
        f'experimental_bearer_token = "{safe_key}"\n'
        f'env_key = "OPENAI_COMPATIBLE_MCP_API_KEY"\n'
        f'wire_api = "chat"\n'
    )
    mcp_block = (
        f"[mcp_servers.{provider_key}]\n"
        f'command = "openai-compatible-mcp"\n'
        f'args = []\n'
        f'\n[mcp_servers.{provider_key}.env]\n'
        f'OPENAI_COMPATIBLE_MCP_API_KEY = "{safe_key}"\n'
        f'OPENAI_COMPATIBLE_MCP_BASE_URL = "{base_url.rstrip("/") or "https://api.deepseek.com"}"\n'
        f'OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL = "{model}"\n'
    )
    return provider_block, mcp_block


# --------------------------------------------------------------------------- #
# Auto-start (Windows Task Scheduler / macOS LaunchAgent / Linux .desktop)
# --------------------------------------------------------------------------- #


def install_autostart() -> dict:
    """Best-effort auto-start: spawn a long-running process per user logon.

    Windows: schtasks (no admin needed if we use /ru current user)
    macOS:   LaunchAgent plist
    Linux:   XDG autostart .desktop
    """
    sysname = platform.system()
    if sysname == "Windows":
        return _autostart_windows()
    if sysname == "Darwin":
        return _autostart_macos()
    return _autostart_linux()


def _autostart_windows() -> dict:
    task_name = "OpenAICompatibleMCPSetupWizard"
    # Check if task already exists
    rc, out, _ = run(["schtasks", "/Query", "/TN", task_name], timeout=10)
    if rc == 0:
        return {"ok": True, "skipped": True, "message": f"任务 {task_name} 已存在"}

    # Create a basic logon task that runs the wizard server (it serves a UI and a long-running MCP server
    # would be a separate concern; for the wizard, we just open the page on logon).
    py = python_exe()
    ps_cmd = (
        f"$a = New-ScheduledTaskAction -Execute '{py}' -Argument '{(WIZARD_DIR / 'server.py')}' "
        f"-WorkingDirectory '{WIZARD_DIR}'; "
        f"$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        f"$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName '{task_name}' -Action $a -Trigger $t -Settings $s -Force"
    )
    rc, out, err = run(
        ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
        timeout=30,
    )
    if rc != 0:
        return {"ok": False, "message": "schtasks 创建失败", "stderr": err}
    return {"ok": True, "message": f"已创建计划任务: {task_name}"}


def _autostart_macos() -> dict:
    label = "com.xiaobaotalks.openai-compatible-mcp.wizard"
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{label}.plist"
    py = python_exe()
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{py}</string>
    <string>{(WIZARD_DIR / 'server.py')}</string>
  </array>
  <key>WorkingDirectory</key><string>{WIZARD_DIR}</string>
  <key>RunAtLoad</key><true/>
</dict></plist>
"""
    plist_path.write_text(content, encoding="utf-8")
    rc, out, err = run(["launchctl", "load", str(plist_path)], timeout=10)
    return {
        "ok": rc == 0,
        "message": f"已创建 LaunchAgent: {plist_path}",
        "stderr": err if rc != 0 else "",
    }


def _autostart_linux() -> dict:
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop = autostart_dir / "openai-compatible-mcp-wizard.desktop"
    py = python_exe()
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name=OpenAI Compatible MCP Setup
Exec={py} {(WIZARD_DIR / 'server.py')}
Terminal=false
X-GNOME-Autostart-enabled=true
""",
        encoding="utf-8",
    )
    return {"ok": True, "message": f"已创建 autostart 入口: {desktop}"}


# --------------------------------------------------------------------------- #
# Launch proxy / claude in a new terminal window
# --------------------------------------------------------------------------- #


def _is_port_listening(host: str, port: int) -> bool:
    """Check if a TCP port is accepting connections (LISTEN/ESTABLISHED) on host."""
    import socket as _s
    with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _spawn_windows(cmd: list[str], cwd: str | None = None, env: dict | None = None) -> tuple[bool, str]:
    """Spawn `cmd` in a brand new console window on Windows."""
    CREATE_NEW_CONSOLE = 0x00000010
    try:
        subprocess.Popen(
            list(cmd),
            cwd=cwd,
            env=env,
            creationflags=CREATE_NEW_CONSOLE,
            close_fds=True,
        )
        return True, "已在新 cmd 窗口启动"
    except FileNotFoundError as e:
        return False, f"找不到可执行文件: {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"启动失败: {e}"


def _spawn_posix(cmd: list[str], cwd: str | None = None, env: dict | None = None) -> tuple[bool, str]:
    """Spawn `cmd` in a new terminal window on macOS/Linux."""
    import shlex
    import shutil

    exports = ""
    for k, v in (env or {}).items():
        if v is None or v == "":
            continue
        exports += f"export {k}={shlex.quote(str(v))}; "
    quoted = " ".join(shlex.quote(c) for c in cmd)
    shell_cmd = f"{exports}{quoted}; echo; echo '[Enter] 关闭此窗口'; read"

    if sys.platform == "darwin":
        try:
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{shell_cmd}" activate'])
            return True, "已在 Terminal 新标签页启动"
        except Exception as e:  # noqa: BLE001
            return False, f"启动失败: {e}"

    for term in ("gnome-terminal", "konsole", "alacritty", "xterm", "x-terminal-emulator"):
        if shutil.which(term):
            try:
                if term == "gnome-terminal":
                    subprocess.Popen([term, "--", "bash", "-c", shell_cmd], cwd=cwd)
                elif term == "konsole":
                    subprocess.Popen([term, "-e", "bash", "-c", shell_cmd], cwd=cwd)
                else:
                    subprocess.Popen([term, "-e", "bash", "-c", shell_cmd], cwd=cwd)
                return True, f"已在 {term} 新窗口启动"
            except Exception:
                continue
    return False, "找不到可用的终端模拟器(请安装 xterm / gnome-terminal)"


def _spawn(cmd: list[str], cwd: str | None = None, env: dict | None = None) -> tuple[bool, str]:
    """平台分发:Windows 走新控制台,POSIX 走新终端窗口。"""
    if sys.platform == "win32":
        return _spawn_windows(cmd, cwd=cwd, env=env)
    return _spawn_posix(cmd, cwd=cwd, env=env)


def _find_claude_launch_cmd() -> "Path | None":
    """从本文件向上找 setup/claude-launch.cmd(开发模式),找不到就返回 None。"""
    p = Path(__file__).resolve().parent
    for _ in range(6):
        for name in ("claude-launch.cmd", "claude-launch.sh"):
            cand = p / "setup" / name
            if cand.is_file():
                return cand
            cand2 = p / name
            if cand2.is_file():
                return cand2
        if p.parent == p:
            break
        p = p.parent
    return None


def start_proxy_in_window() -> dict:
    """POST /api/start-proxy:在**新窗口**启动 Codex 翻译代理 (127.0.0.1:7878)。"""
    if _is_port_listening("127.0.0.1", 7878):
        return {
            "ok": True,
            "skipped": True,
            "message": "127.0.0.1:7878 已在监听,代理应该已经在跑,无需重复启动。",
            "command": [],
        }

    import shutil
    cmd: list[str] | None = None
    if shutil.which("openai-compatible-mcp-proxy"):
        cmd = ["openai-compatible-mcp-proxy"]
    elif shutil.which("openai-compatible-mcp"):
        cmd = ["openai-compatible-mcp", "--proxy"]
    else:
        return {
            "ok": False,
            "error": "找不到 openai-compatible-mcp-proxy,请先 `pip install openai-compatible-mcp`",
            "command": [],
        }

    ok, msg = _spawn(cmd)
    return {"ok": ok, "message": msg, "command": cmd, "skipped": False}


def start_claude_in_window() -> dict:
    """POST /api/start-claude:在新窗口启动 Claude Code,自动注入 DeepSeek env。"""
    launch = _find_claude_launch_cmd()
    if launch and sys.platform == "win32":
        cmd = [str(launch)]
        env = None
        used = f"claude-launch.cmd ({launch})"
    else:
        proxy_cfg = Path.home() / ".openai-compatible-mcp" / "proxy.json"
        api_key = ""
        base = "https://api.deepseek.com"
        if proxy_cfg.is_file():
            try:
                pj = json.loads(proxy_cfg.read_text(encoding="utf-8")) or {}
                api_key = (pj.get("deepseek_api_key") or "").strip()
                base = (pj.get("deepseek_api_base") or base).strip()
            except Exception:
                pass
        base_url = base.rstrip("/") + "/anthropic"
        env = {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_SMALL_FAST_MODEL": "deepseek-v4-pro",
            "CLAUDE_CODE_EFFORT_LEVEL": "max",
        }
        import glob
        import shutil
        claude_exe: str | None = None
        if sys.platform == "win32":
            for cand in [
                shutil.which("claude"),
                shutil.which("claude.cmd"),
                *(glob.glob(r"C:\Users\*\AppData\Local\Microsoft\Windows\WinGet\Packages\anthropic.claude-code_*\anthropic.claude-code\tools\claude.exe") or []),
                *(glob.glob(os.path.expandvars(r"%APPDATA%\npm\claude.cmd")) or []),
                *(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\npm\claude.cmd")) or []),
            ]:
                if cand and os.path.isfile(cand):
                    claude_exe = cand
                    break
        else:
            claude_exe = shutil.which("claude")
        if not claude_exe:
            return {
                "ok": False,
                "error": "找不到 claude 命令,请先 `npm install -g @anthropic-ai/claude-code`",
                "command": [],
            }
        cmd = [claude_exe]
        used = f"claude + 注入 env ({claude_exe})"

    ok, msg = _spawn(cmd, env=env)
    return {"ok": ok, "message": msg, "command": cmd, "used": used}


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #


class Handler(http.server.BaseHTTPRequestHandler):
    # Quieter logs
    def log_message(self, format, *args):  # noqa: A002
        sys.stderr.write(f"[http] {self.address_string()} - {format % args}\n")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"_error": f"invalid JSON: {e}"}

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            if not INDEX_HTML.exists():
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"index.html not found next to server.py")
                return
            data = INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/env":
            self._send_json(200, detect_env())
            return

        if path == "/api/providers":
            self._send_json(200, PROVIDERS)
            return

        if path == "/api/health":
            self._send_json(200, {"ok": True, "ts": time.time()})
            return

        self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        body = self._read_json()

        if path == "/api/install":
            self._send_json(200, install_package())
            return

        if path == "/api/test":
            self._send_json(200, test_connection(
                body.get("provider", "deepseek"),
                body.get("api_key", ""),
                body.get("base_url", ""),
                body.get("model", "deepseek-v4-pro"),
            ))
            return

        if path == "/api/configure":
            try:
                result = configure_clients(
                    provider=body.get("provider", "deepseek"),
                    api_key=body.get("api_key", ""),
                    base_url=body.get("base_url", ""),
                    model=body.get("model", ""),
                    clients=body.get("clients", []),
                    method=body.get("method", "uvx"),
                    codex_base_url=body.get("codex_base_url", ""),
                )
            except Exception as e:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(e)})
                return
            self._send_json(200, result)
            return

        if path == "/api/autostart":
            self._send_json(200, install_autostart())
            return

        if path == "/api/start-proxy":
            self._send_json(200, start_proxy_in_window())
            return

        if path == "/api/start-claude":
            self._send_json(200, start_claude_in_window())
            return

        if path == "/api/open-folder":
            # open the install dir in the OS file manager
            p = body.get("path", str(WIZARD_DIR))
            sysname = platform.system()
            try:
                if sysname == "Windows":
                    os.startfile(p)  # type: ignore[attr-defined]
                elif sysname == "Darwin":
                    subprocess.Popen(["open", p])
                else:
                    subprocess.Popen(["xdg-open", p])
                self._send_json(200, {"ok": True})
            except Exception as e:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(e)})
            return

        self._send_json(404, {"error": "not found", "path": path})


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


def is_port_in_use(port: int) -> bool:
    import socket as _s
    with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((HOST, port))
            return True
        except OSError:
            return False


def main() -> int:
    info(f"Python     : {platform.python_version()}  ({python_exe()})")
    info(f"Working dir: {WIZARD_DIR}")

    if is_port_in_use(PORT):
        info(f"端口 {PORT} 已被占用,假定已有实例在运行,直接打开浏览器")
        # 顺便检查一下 ~/.openai-compatible-mcp/proxy.json 里有没有 API Key,
        # 没有的话提醒用户去浏览器里填,否则 --proxy 起来后转发不到 DeepSeek。
        proxy_cfg = Path.home() / ".openai-compatible-mcp" / "proxy.json"
        if not proxy_cfg.is_file():
            info("⚠ 还没找到 ~/.openai-compatible-mcp/proxy.json 。")
            info("  请在弹出的浏览器向导里填 DeepSeek API Key 后点「保存」,")
            info("  否则稍后跑 openai-compatible-mcp --proxy 会因为缺 Key 无法转发。")
        else:
            try:
                with proxy_cfg.open("r", encoding="utf-8") as f:
                    if not (json.load(f).get("deepseek_api_key") or "").strip():
                        info("⚠ proxy.json 已存在,但 deepseek_api_key 为空。")
                        info("  请在浏览器向导里填 Key 后点「保存」,再重启 --proxy。")
            except Exception:
                info("⚠ proxy.json 读取失败,请在浏览器向导里重新填一次 Key。")
        webbrowser.open(f"http://{HOST}:{PORT}/")
        return 0

    httpd = socketserver.TCPServer((HOST, PORT), Handler)
    info(f"listening on http://{HOST}:{PORT}")

    # Open browser in background, 1.5s delay to let the server start
    def _open():
        time.sleep(1.5)
        webbrowser.open(f"http://{HOST}:{PORT}/")
    threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        info("shutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
