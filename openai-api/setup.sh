#!/usr/bin/env bash
# Bootstrap a venv for the openai-api server.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
echo "Done. To run:"
echo "  source openai-api/.venv/bin/activate"
echo "  cp openai-api/.env.example openai-api/.env   # add your OPENAI_API_KEY"
echo "  PORT=8300 python openai-api/main.py"
