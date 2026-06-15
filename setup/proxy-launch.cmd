@echo off
REM ====================================================================
REM openai-compatible-mcp  -  Codex 翻译代理 启动包装（Windows）
REM
REM 用途: 一键启动 Codex → DeepSeek Responses API 翻译代理
REM       (默认监听 127.0.0.1:7878,转发到 api.deepseek.com)。
REM
REM 行为:
REM   - 优先调用 `openai-compatible-mcp-proxy`(pip install 时自动加到 PATH)
REM   - 端口被占用时打一行提示就退出,不让两个代理互相打架
REM   - 关闭当前 PowerShell 窗口 = 代理停止
REM
REM 用法:
REM   1) 双击本文件即可启动
REM   2) 终端里直接跑:  proxy-launch
REM   3) 把本文件目录加到 PATH 后,任意位置运行
REM ====================================================================
setlocal EnableDelayedExpansion

REM ---------- 0. 探测 7878 端口 ----------
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 7878 -State Listen -ErrorAction SilentlyContinue; if ($c) { Write-Output 'IN_USE' }" >nul 2>&1
for /f %%I in ('powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 7878 -State Listen -ErrorAction SilentlyContinue; if ($c) { 'IN_USE' }"') do set "PORT_STATE=%%I"
if /I "%PORT_STATE%"=="IN_USE" (
    echo [proxy-launch] 7878 端口已被占用,代理应该已经在跑(打开浏览器看 http://127.0.0.1:7878/v1/models 确认)。
    exit /b 0
)

REM ---------- 1. 选命令 ----------
set "PROXY_CMD="
where openai-compatible-mcp-proxy >nul 2>&1
if not errorlevel 1 set "PROXY_CMD=openai-compatible-mcp-proxy"

if not defined PROXY_CMD (
    where openai-compatible-mcp >nul 2>&1
    if not errorlevel 1 set "PROXY_CMD=openai-compatible-mcp"
)

if not defined PROXY_CMD (
    echo [proxy-launch] 找不到 openai-compatible-mcp / openai-compatible-mcp-proxy 命令。
    echo              请先:  pip install openai-compatible-mcp
    pause
    exit /b 1
)

REM ---------- 2. 启动 ----------
echo [proxy-launch] 启动 Codex 翻译代理 (127.0.0.1:7878 ^→ api.deepseek.com)
echo [proxy-launch] 关闭本窗口即可停止代理
echo.
%PROXY_CMD% %*
endlocal
