"""Eval harness — Karpathy-style "measure first".

Every eval case is a tiny YAML: (event, agent, expected_fields). The harness
loads the agent, runs it on the event with no other context, and grades each
expected field. Reports pass/fail + drift over time so you can see whether
prompt edits made things better or worse.

Grade ops supported in the YAML expect: blocks:
  field: value             # exact equality
  field.contains: x        # field is a list and contains x
  field.in: [a, b, c]      # field equals one of these
  field.min_length: N      # field is a list/str with at least N items
  field.max_length: N      # field is a list/str with at most N items
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.agents import REGISTRY
from src.context.builder import build as build_context
from src.config import ROOT
from src.trigger.webhook import load_event

EVALS_DIR = ROOT / "evals" / "cases"


@dataclass
class CaseResult:
    name: str
    agent: str
    pass_count: int = 0
    fail_count: int = 0
    failures: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    raw_output: dict | None = None
    agent_error: str | None = None

    @property
    def passed(self) -> bool:
        return self.fail_count == 0 and self.agent_error is None


# ---- assertion ops -----------------------------------------------------

def _resolve(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _check(output: dict, key: str, expected: Any) -> tuple[bool, str]:
    """Return (passed, message)."""
    if "." in key and key.split(".")[-1] in {"contains", "in", "min_length", "max_length"}:
        path, op = key.rsplit(".", 1)
        actual = _resolve(output, path)
        if op == "contains":
            ok = isinstance(actual, list) and expected in actual
            return ok, f"{path}.contains({expected!r}) — actual={actual!r}"
        if op == "in":
            ok = actual in (expected or [])
            return ok, f"{path}.in({expected!r}) — actual={actual!r}"
        if op == "min_length":
            ok = hasattr(actual, "__len__") and len(actual) >= int(expected)
            return ok, f"{path}.min_length({expected}) — actual_len={len(actual) if hasattr(actual, '__len__') else 'N/A'}"
        if op == "max_length":
            ok = hasattr(actual, "__len__") and len(actual) <= int(expected)
            return ok, f"{path}.max_length({expected}) — actual_len={len(actual) if hasattr(actual, '__len__') else 'N/A'}"

    actual = _resolve(output, key)
    ok = actual == expected
    return ok, f"{key} == {expected!r} — actual={actual!r}"


# ---- core --------------------------------------------------------------

async def run_case(case_path: Path) -> CaseResult:
    case = yaml.safe_load(case_path.read_text())
    name = case["name"]
    agent_name = case["agent"]
    event_path = ROOT / case["event"]
    expectations = case.get("expect", {}) or {}

    AgentCls = REGISTRY.get(agent_name)
    if AgentCls is None:
        return CaseResult(name=name, agent=agent_name,
                          agent_error=f"unknown agent in REGISTRY: {agent_name}")

    event = load_event(event_path)
    ctx = build_context(event, trusted=True)

    t0 = time.time()
    result = await AgentCls().run(ctx)
    duration = time.time() - t0

    cr = CaseResult(name=name, agent=agent_name, duration_s=duration,
                    raw_output=result.output, agent_error=result.error)
    if not result.ok:
        return cr

    for key, expected in expectations.items():
        ok, msg = _check(result.output or {}, key, expected)
        if ok:
            cr.pass_count += 1
        else:
            cr.fail_count += 1
            cr.failures.append(msg)
    return cr


async def run_all(only_agent: str | None = None) -> list[CaseResult]:
    cases = sorted(EVALS_DIR.glob("*.yaml"))
    if only_agent:
        cases = [c for c in cases if yaml.safe_load(c.read_text()).get("agent") == only_agent]
    results: list[CaseResult] = []
    for c in cases:
        results.append(await run_case(c))
    return results


def write_report(results: list[CaseResult], out_path: Path) -> None:
    payload = {
        "ts": time.time(),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "cases": [
            {
                "name": r.name, "agent": r.agent, "passed": r.passed,
                "duration_s": round(r.duration_s, 2),
                "pass_count": r.pass_count, "fail_count": r.fail_count,
                "failures": r.failures, "agent_error": r.agent_error,
            }
            for r in results
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str))


# Sync wrappers for the CLI.
def run_all_sync(only_agent: str | None = None) -> list[CaseResult]:
    return asyncio.run(run_all(only_agent))
