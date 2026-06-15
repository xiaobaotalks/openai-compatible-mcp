@echo off
chcp 65001 >nul 2>&1
REM ====================================================================
REM openai-compatible-mcp  -  一键安装配置脚本（Windows）
REM 双击运行即可，自动完成所有步骤，无需手动输入任何命令。
REM ====================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

REM ---------- 1. 找 Python ----------
echo [1/4] 检测 Python 环境...
set "PY="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "py.exe"
    python
) do (
    if not defined PY if exist "%%~fP" (
        REM 排除 py.exe（它是启动器，不直接可执行脚本）
        echo %%~fP | findstr /i "py.exe" >nul 2>&1
        if errorlevel 1 set "PY=%%~fP"
        if not errorlevel 1 if exist "%%~fP\python.exe" set "PY=%%~fP\python.exe"
    )
)
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [错误] 找不到 Python，请先从 https://www.python.org/downloads/ 安装 Python 3.9+
    echo.
    pause
    exit /b 1
)

REM 检查 Python 版本
for /f "delims=" %%v in ('"%PY%" --version 2^>nul') do set "PYVER=%%v"
echo       使用: !PY! (!PYVER!)

REM ---------- 2. 安装包 ----------
echo [2/4] 安装 openai-compatible-mcp 包（editable 模式）...
"%PY%" -m pip install -e . --quiet
if errorlevel 1 (
    echo [错误] pip install 失败，尝试加 --user
    "%PY%" -m pip install -e . --user --quiet
    if errorlevel 1 (
        echo [错误] 包安装失败，请检查 pip 是否正常。
        echo.
        pause
        exit /b 1
    )
)

REM ---------- 3. 生成配置文件 ----------
echo [3/4] 生成 Claude Code / Claude Desktop / Cursor 的配置文件...

set "API_KEY=sk-39fbf04de3b247c395171198903f4708"

REM 先环境自检
"%PY%" -m openai_compatible_mcp --check 2>&1 | findstr /i "问题 建议"

echo.
echo 正在写入配置文件（可能需要创建目录）...

"%PY%" -m openai_compatible_mcp --install-config --api-key "%API_KEY%" 2>&1
if errorlevel 1 (
    echo [错误] 配置文件写入失败。
    echo.
    pause
    exit /b 1
)

REM ---------- 4. 完成 ----------
echo.
echo [4/4] 全部完成！
echo.
echo =================== 使用说明 ===================
echo.
echo 请完全关闭 Claude Code（不要最小化），然后重新启动。
echo.
echo   - 直接在终端输入:  claude
echo   - 不要点击桌面/开始菜单的登录按钮。
echo   - 如果仍然弹出登录窗口，说明 Claude Code 新版本强制要求官方账号登录，
echo     需要使用 CC Switch 等第三方工具绕过。
echo.
echo 如需重新生成配置，重新双击运行本脚本即可。
echo.
echo ================================================
echo.
pause
