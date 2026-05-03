"""BaseAgent — every specialist agent inherits from this.

v3 (Karpathy-at-OpenAI):
  - Calls go through the LLM Router (provider per-agent, model per-agent).
  - When the routed provider supports Structured Outputs (OpenAI), the agent
    passes the JSON schema and skips the parse-and-retry loop on success.
  - Telemetry stores REAL tokens/cost when the provider returns them; falls
    back to estimates only when the provider is character-heuristic (Claude).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import jsonschema

from src.audit import log as audit
from src.config import MAX_AGENT_RETRIES, PROMPTS_DIR, SCHEMAS_DIR
from src.context.builder import ContextBundle
from src.llm import LLMError, get_router

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    agent: str
    ok: bool
    output: Optional[dict] = None
    error: Optional[str] = None
    raw_reply: Optional[str] = None
    retries: int = 0
    telemetry: Optional[dict] = None
    provider: Optional[str] = None         # which provider answered
    model:    Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "retries": self.retries,
            "telemetry": self.telemetry,
            "provider": self.provider,
            "model":    self.model,
        }


class BaseAgent:
    name: str = "base"
    output_key: str = "base"
    structured_output: bool = True   # set False for agents that emit free text + JSON mix

    def __init__(self):
        self.system_prompt = self._load_prompt()
        self.schema = self._load_schema()

    # ---- loading ----------------------------------------------------

    def _load_prompt(self) -> str:
        path = PROMPTS_DIR / f"{self.name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Missing prompt: {path}")
        return path.read_text()

    def _load_schema(self) -> dict:
        path = SCHEMAS_DIR / f"{self.name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing schema: {path}")
        return json.loads(path.read_text())

    # ---- prompt building --------------------------------------------

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return f"Run the {self.name} agent on the event in your context. Reply ONLY with a fenced ```json block matching the schema."

    def schema_reminder(self) -> str:
        return (
            "Output schema (JSON):\n"
            "```json\n" + json.dumps(self.schema, indent=2) + "\n```\n"
            "Reply with ONE fenced ```json block matching this schema. No prose outside the block."
        )

    def post_validate(self, output: dict, ctx: ContextBundle) -> Optional[str]:
        return None

    # ---- main entry --------------------------------------------------

    async def run(self, ctx: ContextBundle) -> AgentResult:
        router = get_router()
        provider, model = router.provider(self.name)

        audit.log(pipeline_id=ctx.pipeline_id, actor=self.name,
                  action="agent_start", decision="info",
                  payload={"provider": provider.name, "model": model})

        last_error: Optional[str] = None
        last_raw: Optional[str] = None
        agg = {"tokens_in": 0, "tokens_out": 0, "cached_tokens": 0,
               "cost_usd": 0.0, "duration_s": 0.0}
        any_estimated = False

        for attempt in range(MAX_AGENT_RETRIES + 1):
            user_prompt = self.build_user_prompt(ctx)
            if attempt > 0 and last_error:
                user_prompt = (
                    f"PREVIOUS ATTEMPT FAILED VALIDATION: {last_error}\n"
                    "Re-emit ONLY the fenced JSON block, fixing the failure.\n\n"
                    + user_prompt
                )

            full_user = f"{user_prompt}\n\n{self.schema_reminder()}"

            try:
                # Pass the schema only when we want structured outputs AND the
                # provider supports them (only OpenAI today; Claude ignores it).
                schema_arg = self.schema if self.structured_output else None
                result = await provider.call(
                    user_prompt=full_user,
                    system_prompt=self.system_prompt,
                    context_lines=ctx.for_agent(self.name),
                    json_schema=schema_arg,
                    model=model or None,
                )
            except LLMError as exc:
                last_error = f"provider_call_failed: {exc}"
                last_raw = None
                continue

            agg["tokens_in"]    += result.tokens_in
            agg["tokens_out"]   += result.tokens_out
            agg["cached_tokens"] += result.cached_tokens
            agg["cost_usd"]     += result.cost_usd
            agg["duration_s"]   += result.duration_s
            any_estimated = any_estimated or result.estimated
            audit.log(
                pipeline_id=ctx.pipeline_id, actor=self.name,
                action="llm_call", decision="info",
                payload={
                    "attempt": attempt, "provider": result.provider,
                    "model": result.model, "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cached_tokens": result.cached_tokens,
                    "cost_usd": round(result.cost_usd, 6),
                    "duration_s": round(result.duration_s, 3),
                    "estimated": result.estimated,
                },
            )

            raw = result.text
            last_raw = raw

            # Structured-output path: response is already JSON (no fence).
            output = _try_direct_json(raw) or _try_fenced_json(raw)
            if output is None:
                last_error = "no JSON found in reply"
                continue

            try:
                jsonschema.validate(output, self.schema)
            except jsonschema.ValidationError as exc:
                last_error = f"schema_violation: {exc.message}"
                continue

            extra = self.post_validate(output, ctx)
            if extra:
                last_error = extra
                continue

            telemetry_total = {**agg, "estimated": any_estimated}
            telemetry_total["cost_usd"] = round(telemetry_total["cost_usd"], 6)
            telemetry_total["duration_s"] = round(telemetry_total["duration_s"], 3)
            audit.log(
                pipeline_id=ctx.pipeline_id, actor=self.name,
                action="agent_done", decision="success",
                payload={"retries": attempt, "telemetry": telemetry_total,
                         "provider": result.provider, "model": result.model},
            )
            return AgentResult(
                agent=self.name, ok=True, output=output, raw_reply=raw,
                retries=attempt, telemetry=telemetry_total,
                provider=result.provider, model=result.model,
            )

        telemetry_total = {**agg, "estimated": any_estimated}
        telemetry_total["cost_usd"] = round(telemetry_total["cost_usd"], 6)
        telemetry_total["duration_s"] = round(telemetry_total["duration_s"], 3)
        audit.log(
            pipeline_id=ctx.pipeline_id, actor=self.name,
            action="agent_failed", decision="error",
            payload={"error": last_error, "retries": MAX_AGENT_RETRIES,
                     "telemetry": telemetry_total},
        )
        return AgentResult(
            agent=self.name, ok=False, error=last_error, raw_reply=last_raw,
            retries=MAX_AGENT_RETRIES, telemetry=telemetry_total,
            provider=provider.name, model=model,
        )


# ---------------------------------------------------------------------------
# JSON extractors (kept here so BaseAgent has no external coupling).
# ---------------------------------------------------------------------------

def _try_direct_json(text: str) -> Optional[dict]:
    s = (text or "").strip()
    if s.startswith(("{", "[")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _try_fenced_json(text: str) -> Optional[dict]:
    import re
    m = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
