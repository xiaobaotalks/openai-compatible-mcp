@echo off
REM ====================================================================
REM openai-compatible-mcp  -  Claude Code 启动包装（Windows）
REM
REM 用途: 在调用真正的 `claude` 命令前,先把 DeepSeek 网关 + API Key
REM       注入到当前进程的环境变量里,确保 Claude Code 不走官方登录
REM       直接走 DeepSeek。即使 ~/.claude/settings.json 没被读,
REM       这里的系统级 env 一定会生效。
REM
REM 用法:
REM   1) 双击本文件即可启动 Claude Code。
REM   2) 或者在终端直接运行:  claude-launch
REM   3) 或者把本文件目录加入 PATH 后,在任意位置运行 claude-launch。
REM
REM 兼容 Claude Code 任意版本(老 / 新)。
REM ====================================================================
setlocal EnableDelayedExpansion

REM ---------- 0. 找 claude 可执行文件 ----------
set "CLAUDE_EXE="
for %%P in (
    "%LOCALAPPDATA%\Microsoft\Windows\WinGet\Packages\anthropic.claude-code_*\anthropic.claude-code\tools\claude.exe"
    "%LOCALAPPDATA%\Programs\claude\claude.exe"
    "%APPDATA%\npm\claude.cmd"
    "%APPDATA%\npm\claude.exe"
    "%NVM_HOME%\claude.cmd"
    "%ProgramFiles%\nodejs\claude.cmd"
) do (
    if not defined CLAUDE_EXE if exist "%%~fP" set "CLAUDE_EXE=%%~fP"
)
if not defined CLAUDE_EXE (
    where claude >nul 2>&1 && set "CLAUDE_EXE=claude"
)
if not defined CLAUDE_EXE (
    echo [错误] 找不到 claude 命令。请先运行:  npm install -g @anthropic-ai/claude-code
    pause
    exit /b 1
)

REM ---------- 1. 读 API Key ----------
REM 优先: 环境变量 -> DEEPSEEK_API_KEY / OPENAI_COMPATIBLE_MCP_API_KEY
REM 兜底: 从 ~/.claude/settings.json 里读
set "API_KEY="
if defined DEEPSEEK_API_KEY set "API_KEY=%DEEPSEEK_API_KEY%"
if not defined API_KEY if defined OPENAI_COMPATIBLE_MCP_API_KEY set "API_KEY=%OPENAI_COMPATIBLE_MCP_API_KEY%"
if not defined API_KEY (
    if exist "%USERPROFILE%\.claude\settings.json" (
        for /f "usebackq tokens=2 delims=:" %%v in (`findstr /i "ANTHROPIC_AUTH_TOKEN" "%USERPROFILE%\.claude\settings.json"`) do (
            set "API_KEY=%%~v"
        )
    )
)
if not defined API_KEY (
    echo [警告] 没找到 DeepSeek API Key。
    echo         请先通过本项目的 "一键安装" 脚本生成配置,或在系统环境变量里设置 DEEPSEEK_API_KEY。
    echo         现在仍会启动 claude,但会走官方 Anthropic 网关(可能无法登录)。
    echo.
)

REM ---------- 2. 注入 env(覆盖任何残留的官方 env) ----------
set "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic"
set "ANTHROPIC_AUTH_TOKEN=%API_KEY%"
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_MODEL=deepseek-v4-pro"
set "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro"
set "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro"
set "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-pro"
set "ANTHROPIC_SMALL_FAST_MODEL=deepseek-v4-pro"
set "CLAUDE_CODE_EFFORT_LEVEL=max"
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"
set "DISABLE_TELEMETRY=1"

REM 3) 启动
echo [claude-launch] 走 DeepSeek 网关: %ANTHROPIC_BASE_URL%
echo [claude-launch] 启动 claude: %CLAUDE_EXE%
echo.
call "%CLAUDE_EXE%" %*
endlocal
