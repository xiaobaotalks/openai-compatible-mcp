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
WIZARD_DIR = Path(__file__).resolve().parent
INDEX_HTML = WIZARD_DIR / "index.html"

# Defaults
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
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


def _claude_code_settings_path() -> Path:
    """Claude Code uses ~/.claude.json."""
    return Path.home() / ".claude.json"


def _codex_config_path() -> Path:
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "codex" / "config.toml"
    return Path.home() / ".codex" / "config.toml"


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
        p = _claude_code_settings_path()
        existing = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
        merged = _merge_mcp_servers(existing, "openai-compatible", server_cfg)
        _atomic_write_json(p, merged)
        written.append(str(p))

    if "codex" in clients:
        p = _codex_config_path()
        existing_text = ""
        if p.exists():
            existing_text = p.read_text(encoding="utf-8")
        # We need to set OPENAI_COMPATIBLE_MCP_* env vars and have codex pick them up.
        # Since codex reads the env from its own process, we instead point codex to the
        # proxy (if running) or to a local OpenAI-compatible endpoint. For the wizard we
        # write a TOML snippet that adds provider env via a launch wrapper. The simplest
        # is to set base_url and instruct user to set the env var in their shell rc.
        toml = _build_codex_toml(base_url, model, env_key, api_key)
        if existing_text and not existing_text.endswith("\n"):
            existing_text += "\n"
        if existing_text and "[mcp_servers.openai_compatible_mcp]" not in existing_text:
            existing_text += "\n" + toml
        else:
            existing_text = toml
        _atomic_write_text(p, existing_text)
        written.append(str(p))

    return {"ok": True, "files_written": written, "server_cfg": server_cfg}


def _build_codex_toml(base_url: str, model: str, env_key: str, api_key: str) -> str:
    base = base_url.rstrip("/") or "https://api.deepseek.com"
    if not base.endswith("/v1"):
        base = base + "/v1"
    return (
        "# Generated by openai-compatible-mcp setup wizard\n"
        f'OPENAI_COMPATIBLE_MCP_API_KEY = "{api_key}"\n'
        f'OPENAI_COMPATIBLE_MCP_BASE_URL = "{base_url.rstrip("/") or "https://api.deepseek.com"}"\n'
        f'OPENAI_COMPATIBLE_MCP_DEFAULT_MODEL = "{model}"\n'
        f'\n[model_providers.openai_compatible_mcp]\n'
        f'name = "OpenAI Compatible"\n'
        f'base_url = "{base}"\n'
        f'env_key = "{env_key}"\n'
        f'\n[profiles.openai_compatible_mcp]\n'
        f'model = "{model}"\n'
        f'model_provider = "openai_compatible_mcp"\n'
    )


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
                body.get("model", "deepseek-chat"),
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
                )
            except Exception as e:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(e)})
                return
            self._send_json(200, result)
            return

        if path == "/api/autostart":
            self._send_json(200, install_autostart())
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
