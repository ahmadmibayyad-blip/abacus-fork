#!/usr/bin/env bash
# Start Cloner on http://127.0.0.1:8765/ (first run installs everything)
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt
[ -d node_modules ] || npm install --no-audit --no-fund
python -m cloner
