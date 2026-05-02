"""Subprocess wrapper around the local ``claude`` CLI.

Invokes ``claude -p PROMPT --output-format json`` and returns the LLM's
plain-text result string. Caller is responsible for further parsing.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 90.0
_CLI_BIN = "claude"

_available: Optional[bool] = None


class ClaudeCliError(RuntimeError):
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
        logger.exception("claude_cli: unexpected error during availability probe")
        return False


async def is_available(force: bool = False) -> bool:
    """Cached check: is the ``claude`` CLI usable on this host?"""
    global _available
    if _available is None or force:
        _available = await _probe_available()
        logger.info("claude_cli: available=%s", _available)
    return _available


def reset_availability_cache() -> None:
    global _available
    _available = None


async def run_claude(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    attachments: Optional[list[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Invoke ``claude -p PROMPT`` and return the LLM's text result.

    Raises ``ClaudeCliError`` on failure, timeout, or malformed envelope.
    """
    import os

    full_prompt = user_prompt
    if attachments:
        suffix = " ".join(f"@{p}" for p in attachments)
        full_prompt = f"{user_prompt}\n\n{suffix}" if user_prompt else suffix

    args: list[str] = [_CLI_BIN, "-p", full_prompt, "--output-format", "json"]
    if system_prompt:
        args += ["--append-system-prompt", system_prompt]
    if attachments:
        seen_dirs: set[str] = set()
        for path in attachments:
            parent = os.path.dirname(os.path.abspath(path))
            if parent and parent not in seen_dirs:
                seen_dirs.add(parent)
                args += ["--add-dir", parent]
        args += ["--permission-mode", "bypassPermissions"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ClaudeCliError("claude CLI not found on PATH") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise ClaudeCliError(f"claude CLI timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude CLI exited {proc.returncode}: {stderr_b.decode(errors='replace')[:400]}"
        )

    stdout = stdout_b.decode(errors="replace")
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(
            f"claude CLI returned non-JSON output: {stdout[:200]}"
        ) from exc

    if not isinstance(envelope, dict):
        raise ClaudeCliError("claude CLI envelope is not an object")

    if envelope.get("is_error"):
        raise ClaudeCliError(
            f"claude CLI reported error: {envelope.get('result') or envelope.get('subtype')}"
        )

    result = envelope.get("result")
    if not isinstance(result, str):
        raise ClaudeCliError("claude CLI envelope missing string 'result' field")

    return result
