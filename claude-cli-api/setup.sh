#!/bin/bash
set -e

python3 -m venv .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" pydantic
echo "Setup done. Run: source .venv/bin/activate && python main.py"
