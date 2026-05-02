import os

PLANNER_BACKEND = os.getenv("PLANNER_BACKEND", "auto")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-sonnet-4-6")
HTTP_PORT = int(os.getenv("PORT", "8200"))
