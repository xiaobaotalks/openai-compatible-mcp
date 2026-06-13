#!/usr/bin/env bash
# openai-compatible-mcp  -  one-click setup wizard (macOS / Linux)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

PY=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$(command -v "$candidate")"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[error] Python 3.9+ not found."
    echo "        macOS:  brew install python@3.12"
    echo "        Ubuntu: sudo apt install python3"
    exit 1
fi

echo "[setup] Using Python: $PY"
exec "$PY" "$DIR/server.py" "$@"
