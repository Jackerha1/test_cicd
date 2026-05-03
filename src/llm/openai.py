"""OpenAI provider — talks to the local openai-api FastAPI server.

Karpathy moves taken here:
  - REAL token usage from the response.
  - Structured Outputs: when `json_schema` is passed, the server forces the
    model to emit a schema-conforming JSON. The agent's parse-and-retry loop
    becomes redundant on this path.
  - Real cached_tokens from prompt caching.
  - Cost computed from real token counts using current OpenAI prices.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from src.llm.base import CallResult, LLMError, LLMProvider

# As of 2026-Q1; adjust when prices change.
PRICES = {
    # model_name: (input_per_1k, output_per_1k, cached_per_1k)
    "gpt-5":         (0.005, 0.015, 0.0025),
    "gpt-5-mini":    (0.0006, 0.0024, 0.0003),
    "gpt-5-nano":    (0.0002, 0.0008, 0.0001),
    "o3-mini":       (0.0011, 0.0044, 0.00055),
}
DEFAULT_PRICE = (0.005, 0.015, 0.0025)


def _price(model: str, tin: int, tout: int, cached: int) -> float:
    pin, pout, pcached = PRICES.get(model, DEFAULT_PRICE)
    real_in = max(0, tin - cached)
    return ((real_in / 1000) * pin
            + (cached / 1000) * pcached
            + (tout / 1000) * pout)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, base_url: Optional[str] = None, default_timeout: float = 120):
        self.base_url = (base_url or os.getenv("OPENAI_API_URL", "http://localhost:8300")).rstrip("/")
        self.default_timeout = default_timeout

    async def call(
        self, *,
        user_prompt: str, system_prompt: Optional[str] = None,
        context_lines: Optional[list[str]] = None,
        json_schema: Optional[dict] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CallResult:
        payload: dict = {"message": user_prompt, "context": context_lines or []}
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if json_schema:
            payload["json_schema"] = json_schema
        if model:
            payload["model"] = model

        try:
            async with httpx.AsyncClient(timeout=timeout or self.default_timeout) as cli:
                r = await cli.post(f"{self.base_url}/chat", json=payload)
                r.raise_for_status()
                body = r.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"openai provider call failed: {exc}") from exc

        usage = body.get("usage") or {}
        tin = int(usage.get("tokens_in", 0))
        tout = int(usage.get("tokens_out", 0))
        cached = int(usage.get("cached_tokens", 0))
        used_model = usage.get("model", model or "unknown")
        return CallResult(
            text=body.get("reply_text", ""),
            provider=self.name, model=used_model,
            tokens_in=tin, tokens_out=tout, cached_tokens=cached,
            cost_usd=_price(used_model, tin, tout, cached),
            duration_s=float(usage.get("duration_s", 0.0)),
            estimated=False,
        )

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(f"{self.base_url}/health")
                r.raise_for_status()
                return r.json() | {"provider": self.name}
        except httpx.HTTPError as exc:
            raise LLMError(f"openai unreachable: {exc}") from exc
