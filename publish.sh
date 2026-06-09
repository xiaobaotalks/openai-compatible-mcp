#!/usr/bin/env bash
# openai-compatible-mcp  -  one-shot publish script (macOS / Linux)
set -e

REPO_URL="https://github.com/xiaobaotalks/openai-compatible-mcp.git"
BRANCH="main"

echo
echo "=== [1/5] Checking git..."
command -v git >/dev/null 2>&1 || { echo "ERROR: git is not installed."; exit 1; }

echo
echo "=== [2/5] Initializing repository..."
if [ ! -d .git ]; then
    git init -b "$BRANCH"
fi

echo
echo "=== [3/5] Configuring git user (only if not set globally)..."
if ! git config user.name >/dev/null 2>&1; then
    read -rp "Enter your GitHub username: " GIT_USER
    read -rp "Enter your GitHub email: " GIT_EMAIL
    git config user.name "$GIT_USER"
    git config user.email "$GIT_EMAIL"
fi

echo
echo "=== [4/5] Staging and committing..."
git add .
git status --short
git commit -m "Initial release: openai-compatible-mcp v0.1.0" || echo "Nothing to commit, continuing..."

echo
echo "=== [5/5] Pushing to $REPO_URL ..."
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"
git push -u origin "$BRANCH"

echo
echo "=== DONE.  https://github.com/xiaobaotalks/openai-compatible-mcp"
