"""HTTP client for the local claude-cli-api server.

The server (claude-cli-api/main.py) wraps the `claude` CLI behind POST /chat.
This module is the single chokepoint through which every agent talks to Claude.
That gives us one place to inject retries, timeout, JSON-extraction, and
audit logging.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from src.config import CLAUDE_CALL_TIMEOUT, CLAUDE_CLI_API_URL

logger = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


class ClaudeClientError(RuntimeError):
    """Raised when the underlying Claude CLI call fails."""


async def call_claude(
    *,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    context_lines: Optional[list[str]] = None,
    attachments: Optional[list[str]] = None,
    timeout: Optional[float] = None,
) -> str:
    """Send a prompt to claude-cli-api and return the raw text reply."""
    return (await call_claude_with_telemetry(
        user_prompt=user_prompt, system_prompt=system_prompt,
        context_lines=context_lines, attachments=attachments, timeout=timeout,
    ))[0]


async def call_claude_with_telemetry(
    *,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    context_lines: Optional[list[str]] = None,
    attachments: Optional[list[str]] = None,
    timeout: Optional[float] = None,
) -> tuple[str, "CallTelemetry"]:
    """Same as call_claude but also returns token/cost telemetry."""
    import time as _t
    from src.telemetry.tokens import estimate

    payload = {
        "message": user_prompt,
        "context": context_lines or [],
    }
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if attachments:
        payload["attachments"] = attachments

    url = f"{CLAUDE_CLI_API_URL.rstrip('/')}/chat"

    prompt_chars = (
        len(user_prompt or "")
        + len(system_prompt or "")
        + sum(len(c) for c in (context_lines or []))
    )

    t0 = _t.time()
    try:
        async with httpx.AsyncClient(timeout=timeout or CLAUDE_CALL_TIMEOUT) as cli:
            r = await cli.post(url, json=payload)
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as exc:
        raise ClaudeClientError(f"Claude CLI API call failed: {exc}") from exc
    dt = _t.time() - t0

    reply = body.get("reply_text", "")
    if not isinstance(reply, str):
        raise ClaudeClientError("claude-cli-api returned non-string reply_text")

    telem = estimate(prompt_chars=prompt_chars, reply_chars=len(reply), duration_s=dt)
    return reply, telem


def extract_json(text: str) -> Optional[dict]:
    """Pull a JSON object/array out of an LLM reply.

    Tries fenced ```json blocks first, then falls back to the entire body.
    Returns None when nothing parses cleanly.
    """
    m = _FENCED_JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.warning("claude_client: fenced JSON failed to parse")
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return None


async def health_check() -> dict:
    """Probe /health on claude-cli-api. Returns the raw body or raises."""
    url = f"{CLAUDE_CLI_API_URL.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        raise ClaudeClientError(f"claude-cli-api unreachable: {exc}") from exc
