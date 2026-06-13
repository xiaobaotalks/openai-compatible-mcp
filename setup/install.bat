@echo off
REM ====================================================================
REM openai-compatible-mcp  -  one-click setup wizard (Windows)
REM Double-click this file. The browser will open automatically.
REM ====================================================================
setlocal
cd /d "%~dp0"

REM Prefer Python 3.12 / 3.11 from common install locations
set "PY="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "py.exe"
) do (
    if not defined PY if exist %%~fP set "PY=%%~fP"
)
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [error] Python not found. Please install Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [setup] Using Python: %PY%
"%PY%" "%~dp0server.py" %*
endlocal
