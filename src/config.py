"""Central configuration loaded from .env / environment."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CLAUDE_CLI_API_URL = os.getenv("CLAUDE_CLI_API_URL", "http://localhost:8765")
CLAUDE_CALL_TIMEOUT = float(os.getenv("CLAUDE_CALL_TIMEOUT", "180"))

WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(ROOT / "artifacts"))).resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_DB_PATH = Path(os.getenv("AUDIT_DB_PATH", str(ROOT / "logs" / "audit.db"))).resolve()
AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SANDBOX_MODE = os.getenv("SANDBOX_MODE", "subprocess")  # "subprocess" | "docker"
MAX_AGENT_RETRIES = int(os.getenv("MAX_AGENT_RETRIES", "2"))
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() == "true"

# Where prompts / schemas / policies live
PROMPTS_DIR = ROOT / "prompts"
SCHEMAS_DIR = ROOT / "schemas"
POLICIES_DIR = ROOT / "policies"
