#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

echo "Starting AI Bug Fix Orchestrator on http://0.0.0.0:8000"
# python -m app
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
