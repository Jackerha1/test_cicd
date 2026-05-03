"""Subprocess wrapper around the local ``gemini`` CLI.

Invokes ``gemini -p PROMPT --output-format json --yolo`` and returns the LLM's
plain-text result string.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 90.0
_CLI_BIN = "gemini"

_available: Optional[bool] = None


class GeminiCliError(RuntimeError):
    pass


async def _probe_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            _CLI_BIN,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return False
        return proc.returncode == 0
    except (FileNotFoundError, PermissionError):
        return False
    except Exception:
        logger.exception("gemini_cli: unexpected error during availability probe")
        return False


async def is_available(force: bool = False) -> bool:
    """Cached check: is the ``gemini`` CLI usable on this host?"""
    global _available
    if _available is None or force:
        _available = await _probe_available()
        logger.info("gemini_cli: available=%s", _available)
    return _available


async def run_gemini(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    attachments: Optional[list[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Invoke ``gemini -p PROMPT --yolo`` and return the LLM's text result."""
    
    # Merge system prompt into the main prompt since gemini CLI doesn't support --system
    final_prompt = ""
    if system_prompt:
        final_prompt += f"System: {system_prompt}\n\n"
    
    final_prompt += user_prompt

    if attachments:
        suffix = " ".join(f"@{p}" for p in attachments)
        final_prompt = f"{final_prompt}\n\n{suffix}" if final_prompt else suffix

    args: list[str] = [
        _CLI_BIN, "-p", final_prompt,
        "--output-format", "json",
        "--yolo",
        "--skip-trust",        # don't refuse based on workdir trust state (we're a server)
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise GeminiCliError("gemini CLI not found on PATH") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise GeminiCliError(f"gemini CLI timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise GeminiCliError(
            f"gemini CLI exited {proc.returncode}: {stderr_b.decode(errors='replace')[:400]}"
        )

    stdout = stdout_b.decode(errors="replace")

    # Gemini sometimes prepends warnings ("MCP issues detected...") before the
    # JSON envelope. Find the first '{' and parse from there.
    brace = stdout.find("{")
    json_blob = stdout[brace:] if brace >= 0 else stdout

    try:
        envelope = json.loads(json_blob)
    except json.JSONDecodeError:
        return stdout.strip()

    if not isinstance(envelope, dict):
        return stdout.strip()

    # Gemini envelope shape: {"session_id":..., "response":"<text>", "stats":...}
    # Try the documented keys in order.
    for k in ("response", "result", "text", "content"):
        v = envelope.get(k)
        if isinstance(v, str) and v.strip():
            return v

    return stdout.strip()
