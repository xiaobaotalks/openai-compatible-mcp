@echo off
REM ====================================================================
REM openai-compatible-mcp  -  one-shot publish script
REM Run this from the project root after `winget install Git.Git`
REM ====================================================================
setlocal

set REPO_URL=https://github.com/xiaobaotalks/openai-compatible-mcp.git
set BRANCH=main

echo.
echo === [1/5] Checking git...
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not installed. Run:  winget install Git.Git
    echo Then re-open this terminal and run this script again.
    exit /b 1
)

echo.
echo === [2/5] Initializing repository...
if not exist .git (
    git init -b %BRANCH%
)

echo.
echo === [3/5] Configuring git user (only if not set globally)...
git config user.name >nul 2>&1
if errorlevel 1 (
    set /p GIT_USER="Enter your GitHub username: "
    set /p GIT_EMAIL="Enter your GitHub email: "
    git config user.name "%GIT_USER%"
    git config user.email "%GIT_EMAIL%"
)

echo.
echo === [4/5] Staging and committing...
git add .
git status --short
git commit -m "Initial release: openai-compatible-mcp v0.1.0" || (
    echo Nothing to commit, continuing...
)

echo.
echo === [5/5] Pushing to %REPO_URL% ...
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git push -u origin %BRANCH%

if errorlevel 1 (
    echo.
    echo Push failed. Common causes:
    echo   1) The repo on GitHub is empty (good - you should be able to push)
    echo   2) Authentication required - make sure you are signed in to GitHub:
    echo        gh auth login
    echo        OR configure a Personal Access Token as the remote password
    echo   3) Branch protection rules on the remote
    exit /b 1
)

echo.
echo === DONE.  https://github.com/xiaobaotalks/openai-compatible-mcp
endlocal
