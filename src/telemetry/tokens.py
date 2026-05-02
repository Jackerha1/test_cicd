"""Token / cost telemetry.

Karpathy: "tokens are money and latency." We don't have direct access to the
provider's usage object (the wrapper API only forwards reply_text), so we
estimate using a simple character-count heuristic. Estimates are tagged
`estimated: true` so anyone reading the audit can tell.

Per-call cost is logged to the audit DB and pipeline totals are queryable via
`ai-cicd cost <pipeline_id>`.
"""
from __future__ import annotations

from dataclasses import dataclass

# Sonnet pricing as of 2026-Q1 (USD per 1K tokens) — adjust if the API changes.
PRICE_INPUT_PER_1K = 0.003
PRICE_OUTPUT_PER_1K = 0.015

# Rough heuristic: 1 token ≈ 3.5 chars for English.
CHARS_PER_TOKEN = 3.5


@dataclass
class CallTelemetry:
    tokens_in:    int
    tokens_out:   int
    cost_usd:     float
    duration_s:   float
    estimated:    bool = True

    def to_dict(self) -> dict:
        return {
            "tokens_in":  self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd":   round(self.cost_usd, 6),
            "duration_s": round(self.duration_s, 3),
            "estimated":  self.estimated,
        }


def estimate(prompt_chars: int, reply_chars: int, duration_s: float) -> CallTelemetry:
    tin = max(1, int(prompt_chars / CHARS_PER_TOKEN))
    tout = max(1, int(reply_chars / CHARS_PER_TOKEN))
    cost = (tin / 1000) * PRICE_INPUT_PER_1K + (tout / 1000) * PRICE_OUTPUT_PER_1K
    return CallTelemetry(tokens_in=tin, tokens_out=tout, cost_usd=cost,
                         duration_s=duration_s, estimated=True)
