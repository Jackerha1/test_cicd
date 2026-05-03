"""Standalone planner — calls Claude CLI, returns reply + optional JSON plan.

Stripped from Flowboard: no DB/SQLModel dependency.
Context lines (board state, mentions, etc.) are passed in by the caller.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional

import claude_cli
import gemini_cli
from config import PLANNER_BACKEND

logger = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant.

When the user describes intent that involves creating a structured plan or pipeline,
respond conversationally in one or two short sentences, then append a fenced JSON block:

```json
{
  "nodes": [
    {"tmp_id": "a", "type": "task", "params": {"description": "…"}}
  ],
  "edges": [
    {"from": "a", "to": "b", "kind": "depends"}
  ]
}
```

If no structured plan is appropriate, omit the JSON block entirely.
Never emit prose inside the JSON block.
"""


def _extract_plan(text: str) -> tuple[str, Optional[dict]]:
    """Extract fenced JSON plan from LLM response. Returns (clean_text, plan|None)."""
    m = _FENCED_JSON_RE.search(text)
    if m:
        raw = m.group(1)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("planner: fenced JSON failed to parse")
            return text, None
        if not _is_valid_plan(parsed):
            logger.warning("planner: plan JSON fails shape check")
            return text, None
        cleaned = (text[: m.start()] + text[m.end() :]).strip()
        return cleaned or text, parsed

    # Fallback: entire body is JSON
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None and _is_valid_plan(parsed):
            return "", parsed

    return text, None


def _is_valid_plan(plan: Any) -> bool:
    if not isinstance(plan, dict):
        return False
    nodes = plan.get("nodes")
    if not isinstance(nodes, list):
        return False
    for n in nodes:
        if not isinstance(n, dict):
            return False
    edges = plan.get("edges", [])
    if not isinstance(edges, list):
        return False
    for e in edges:
        if not isinstance(e, dict):
            return False
    return True


def _mock_reply(user_text: str) -> str:
    preview = user_text.strip()
    if len(preview) > 80:
        preview = preview[:77] + "…"
    return (
        f'Noted: "{preview}". '
        "Planner stub — set PLANNER_BACKEND to 'claude', 'gemini' (or use 'auto') "
        "to enable real planning."
    )


async def generate_reply(
    user_text: str,
    context_lines: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    backend_override: Optional[str] = None,
) -> dict:
    """Returns ``{"reply_text": str, "plan": dict | None, "_backend_used": str}``.

    Args:
        user_text: The user's message.
        context_lines: Extra context lines appended to the prompt.
        system_prompt: Override the default system prompt.
        attachments: List of file paths to attach.
        backend_override: per-call override of the backend ("claude" | "gemini" | "auto" | "mock").
    """
    backend = (backend_override or PLANNER_BACKEND or "auto").lower()

    if backend == "mock":
        return {"reply_text": _mock_reply(user_text), "plan": None, "_backend_used": "mock"}

    parts = [user_text.strip() or ""]
    if context_lines:
        parts.append("\nContext:\n" + "\n".join(context_lines))
    prompt = "\n".join(p for p in parts if p)
    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    raw = None
    error_msg = None
    backend_used = None

    # Determine which CLI to use. Per-call override is hard: "claude" means
    # claude-only; "gemini" means gemini-only. "auto" tries both.
    use_claude = backend in ("claude", "cli", "auto")
    use_gemini = backend in ("gemini", "auto")
    # When backend is explicitly chosen, skip the cached availability probe and
    # just attempt the call — the wrapper raises on real failure. This is the
    # production path: the Router has already made an explicit choice.
    explicit = backend in ("claude", "gemini")

    if use_claude and (explicit or await claude_cli.is_available()):
        try:
            raw = await claude_cli.run_claude(
                user_prompt=prompt,
                system_prompt=sys_prompt,
                attachments=attachments,
            )
            backend_used = "claude"
        except claude_cli.ClaudeCliError as exc:
            logger.warning("planner: claude CLI failed (%s)", exc)
            error_msg = str(exc)

    if raw is None and use_gemini and (explicit or await gemini_cli.is_available()):
        try:
            raw = await gemini_cli.run_gemini(
                user_prompt=prompt,
                system_prompt=sys_prompt,
                attachments=attachments,
            )
            backend_used = "gemini"
        except gemini_cli.GeminiCliError as exc:
            logger.warning("planner: gemini CLI failed (%s)", exc)
            error_msg = str(exc)

    if raw is None:
        if backend != "auto":
            return {
                "reply_text": f"(planner unavailable: {error_msg or 'CLI not found'})",
                "plan": None,
                "_backend_used": backend or "unknown",
            }
        return {"reply_text": _mock_reply(user_text), "plan": None, "_backend_used": "mock"}

    reply_text, plan = _extract_plan(raw)
    if not reply_text.strip():
        reply_text = "Plan proposed."
    return {"reply_text": reply_text, "plan": plan, "_backend_used": backend_used}
