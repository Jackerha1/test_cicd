"""Provider interface.

Every concrete provider returns a CallResult with REAL tokens / cost / latency
(or estimated if the underlying API doesn't expose them, in which case the
estimated flag is True).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMError(RuntimeError):
    pass


@dataclass
class CallResult:
    text:          str
    provider:      str       # "claude" | "openai" | ...
    model:         str
    tokens_in:     int
    tokens_out:    int
    cached_tokens: int
    cost_usd:      float
    duration_s:    float
    estimated:     bool      # True if any of (tokens, cost) is heuristic


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def call(
        self,
        *,
        user_prompt:   str,
        system_prompt: Optional[str] = None,
        context_lines: Optional[list[str]] = None,
        json_schema:   Optional[dict] = None,
        model:         Optional[str] = None,
        timeout:       Optional[float] = None,
    ) -> CallResult:
        ...

    @abstractmethod
    async def health(self) -> dict:
        ...
