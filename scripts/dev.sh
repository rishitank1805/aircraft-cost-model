#!/usr/bin/env bash
# Development mode: every saved change shows up in the browser without restarting anything.
#   - API on http://127.0.0.1:8000, restarts itself when src/ or data/reference/ changes
#   - Pages on http://localhost:5173, update instantly when frontend/ changes (open this one)
# Stop both with Ctrl + C.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python scripts/run_explorer.py --reload &
API=$!
trap 'kill $API 2>/dev/null' EXIT INT TERM
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
