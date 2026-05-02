"""BaseAgent — every specialist agent inherits from this.

Responsibilities:
  - Load its own system prompt (from prompts/<name>.md) and JSON schema.
  - Build a user prompt from the context bundle.
  - Call Claude CLI through the single chokepoint (claude_client).
  - Parse the JSON output, validate against the schema.
  - Log to audit before/after the call.
  - Retry once on validation/parse failure with a tightened reminder.

Subclasses override `name`, `output_key`, optionally `build_user_prompt`, and
optionally `post_validate` (extra rules beyond JSON schema).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import jsonschema

from src.audit import log as audit
from src.claude_client import ClaudeClientError, call_claude_with_telemetry, extract_json
from src.config import MAX_AGENT_RETRIES, PROMPTS_DIR, SCHEMAS_DIR
from src.context.builder import ContextBundle

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    agent: str
    ok: bool
    output: Optional[dict] = None
    error: Optional[str] = None
    raw_reply: Optional[str] = None
    retries: int = 0
    telemetry: Optional[dict] = None   # accumulated tokens/cost across attempts

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "retries": self.retries,
            "telemetry": self.telemetry,
        }


class BaseAgent:
    name: str = "base"          # short slug; matches prompts/<name>.md and schemas/<name>.json
    output_key: str = "base"    # how this agent's output is keyed in ContextBundle.prior_outputs

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

    # ---- prompt building (subclasses can override) ------------------

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        """Default: a one-line task statement; subclasses may add specifics."""
        return f"Run the {self.name} agent on the event in your context. Reply ONLY with a fenced ```json block matching the schema."

    def schema_reminder(self) -> str:
        """Embedded in the user prompt so the model sees the exact contract."""
        return (
            "Output schema (JSON):\n"
            "```json\n" + json.dumps(self.schema, indent=2) + "\n```\n"
            "Reply with ONE fenced ```json block matching this schema. No prose outside the block."
        )

    # ---- post-call validation hook ---------------------------------

    def post_validate(self, output: dict, ctx: ContextBundle) -> Optional[str]:
        """Extra checks beyond JSON schema. Return None on pass, error string on fail."""
        return None

    # ---- main entry --------------------------------------------------

    async def run(self, ctx: ContextBundle) -> AgentResult:
        audit.log(
            pipeline_id=ctx.pipeline_id,
            actor=self.name,
            action="agent_start",
            decision="info",
        )

        last_error: Optional[str] = None
        last_raw: Optional[str] = None
        agg_tokens_in = 0
        agg_tokens_out = 0
        agg_cost = 0.0
        agg_duration = 0.0

        for attempt in range(MAX_AGENT_RETRIES + 1):
            user_prompt = self.build_user_prompt(ctx)
            if attempt > 0 and last_error:
                user_prompt = (
                    f"PREVIOUS ATTEMPT FAILED VALIDATION: {last_error}\n"
                    f"Re-emit ONLY the fenced JSON block, fixing the failure.\n\n"
                    + user_prompt
                )

            full_user = f"{user_prompt}\n\n{self.schema_reminder()}"

            try:
                raw, telem = await call_claude_with_telemetry(
                    user_prompt=full_user,
                    system_prompt=self.system_prompt,
                    context_lines=ctx.for_agent(self.name),
                )
            except ClaudeClientError as exc:
                last_error = f"claude_call_failed: {exc}"
                last_raw = None
                continue

            agg_tokens_in += telem.tokens_in
            agg_tokens_out += telem.tokens_out
            agg_cost += telem.cost_usd
            agg_duration += telem.duration_s
            audit.log(
                pipeline_id=ctx.pipeline_id, actor=self.name,
                action="claude_call", decision="info",
                payload={"attempt": attempt, **telem.to_dict()},
            )

            last_raw = raw
            output = extract_json(raw)
            if output is None:
                last_error = "no JSON block found in reply"
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

            telemetry_total = {
                "tokens_in":  agg_tokens_in,
                "tokens_out": agg_tokens_out,
                "cost_usd":   round(agg_cost, 6),
                "duration_s": round(agg_duration, 3),
                "estimated":  True,
            }
            audit.log(
                pipeline_id=ctx.pipeline_id,
                actor=self.name,
                action="agent_done",
                decision="success",
                payload={"retries": attempt, "telemetry": telemetry_total},
            )
            return AgentResult(agent=self.name, ok=True, output=output,
                               raw_reply=raw, retries=attempt,
                               telemetry=telemetry_total)

        telemetry_total = {
            "tokens_in":  agg_tokens_in,
            "tokens_out": agg_tokens_out,
            "cost_usd":   round(agg_cost, 6),
            "duration_s": round(agg_duration, 3),
            "estimated":  True,
        }
        audit.log(
            pipeline_id=ctx.pipeline_id,
            actor=self.name,
            action="agent_failed",
            decision="error",
            payload={"error": last_error, "retries": MAX_AGENT_RETRIES, "telemetry": telemetry_total},
        )
        return AgentResult(agent=self.name, ok=False, error=last_error,
                           raw_reply=last_raw, retries=MAX_AGENT_RETRIES,
                           telemetry=telemetry_total)
