"""Gemini provider — calls the same claude-cli-api endpoint with backend=gemini.

Karpathy framing: one gateway (claude-cli-api) wraps both CLIs, so the pipeline
side has a single network dependency. The provider just sets `backend=gemini`
in the request body and the gateway routes to the right wrapper.
"""
from __future__ import annotations

from typing import Optional

import httpx

from src.config import CLAUDE_CALL_TIMEOUT, CLAUDE_CLI_API_URL
from src.llm.base import CallResult, LLMError, LLMProvider
from src.telemetry.tokens import estimate


class GeminiProvider(LLMProvider):
    name = "gemini"

    async def call(
        self, *,
        user_prompt: str, system_prompt: Optional[str] = None,
        context_lines: Optional[list[str]] = None,
        json_schema: Optional[dict] = None,    # advisory; CLI doesn't enforce
        model: Optional[str] = None,           # gemini CLI picks its default
        timeout: Optional[float] = None,
    ) -> CallResult:
        import time as _t
        payload: dict = {
            "message": user_prompt,
            "context": context_lines or [],
            "backend": "gemini",
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if json_schema:
            payload["json_schema"] = json_schema    # advisory hint for the gateway

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
            raise LLMError(f"gemini provider call failed: {exc}") from exc
        dt = _t.time() - t0

        reply = body.get("reply_text", "")
        if not isinstance(reply, str):
            raise LLMError("claude-cli-api returned non-string reply_text for gemini call")

        usage = body.get("usage") or {}
        backend_used = usage.get("backend", "gemini")
        if backend_used != "gemini":
            raise LLMError(f"requested backend=gemini but gateway used {backend_used!r}")

        telem = estimate(prompt_chars=prompt_chars, reply_chars=len(reply), duration_s=dt)
        return CallResult(
            text=reply, provider=self.name, model=model or "gemini-default",
            tokens_in=telem.tokens_in, tokens_out=telem.tokens_out,
            cached_tokens=0, cost_usd=telem.cost_usd, duration_s=dt,
            estimated=True,
        )

    async def health(self) -> dict:
        url = f"{CLAUDE_CLI_API_URL.rstrip('/')}/health"
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(url)
                r.raise_for_status()
                body = r.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"gemini gateway unreachable: {exc}") from exc
        return {
            "provider": self.name,
            "available": bool(body.get("gemini_cli_available")),
            "gateway":   "claude-cli-api",
        }
