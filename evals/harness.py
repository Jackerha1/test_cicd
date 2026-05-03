"""Eval harness — Karpathy "measure first".

Each eval case is a tiny YAML. Two `target` types:

  target: agent             # legacy default; uses `agent: <name>` field
    runs the named agent end-to-end through the LLM provider, grades output

  target: policy_engine     # new — DETERMINISTIC, no LLM cost
    runs Policy Engine `classify(files, diff)` against the event,
    grades the resulting verdict (rule_id, risk_level, block, ...)

Grade ops in `expect:` blocks (work for both targets):
  field: value             exact equality
  field.contains: x        list contains
  field.in: [a, b, c]      one-of
  field.min_length: N      list/str length floor
  field.max_length: N      list/str length ceiling
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
from src.policy_engine.engine import classify as classify_policy
from src.trigger.webhook import load_event

EVALS_DIR = ROOT / "evals" / "cases"


@dataclass
class CaseResult:
    name: str
    agent: str               # for policy_engine cases this is "policy_engine"
    target: str = "agent"
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


# ---- runners -----------------------------------------------------------

async def _run_agent_case(case: dict) -> CaseResult:
    name = case["name"]
    agent_name = case["agent"]
    event_path = ROOT / case["event"]
    expectations = case.get("expect", {}) or {}

    AgentCls = REGISTRY.get(agent_name)
    if AgentCls is None:
        return CaseResult(name=name, agent=agent_name, target="agent",
                          agent_error=f"unknown agent in REGISTRY: {agent_name}")

    event = load_event(event_path)
    ctx = build_context(event, trusted=True)

    t0 = time.time()
    result = await AgentCls().run(ctx)
    duration = time.time() - t0

    cr = CaseResult(name=name, agent=agent_name, target="agent",
                    duration_s=duration, raw_output=result.output,
                    agent_error=result.error)
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


def _run_policy_case(case: dict) -> CaseResult:
    """Deterministic — no LLM, no async needed."""
    name = case["name"]
    event_path = ROOT / case["event"]
    expectations = case.get("expect", {}) or {}

    event = load_event(event_path)

    t0 = time.time()
    verdict = classify_policy(event.files_changed, diff=event.diff,
                              pipeline_id=f"eval-{name}")
    duration = time.time() - t0

    cr = CaseResult(name=name, agent="policy_engine", target="policy_engine",
                    duration_s=duration, raw_output=verdict.to_dict())
    for key, expected in expectations.items():
        ok, msg = _check(verdict.to_dict(), key, expected)
        if ok:
            cr.pass_count += 1
        else:
            cr.fail_count += 1
            cr.failures.append(msg)
    return cr


async def run_case(case_path: Path) -> CaseResult:
    case = yaml.safe_load(case_path.read_text())
    target = case.get("target", "agent")
    if target == "policy_engine":
        return _run_policy_case(case)
    if target == "agent":
        return await _run_agent_case(case)
    return CaseResult(name=case.get("name", case_path.stem),
                      agent=case.get("agent", "?"), target=target,
                      agent_error=f"unknown target {target!r}")


# ---- batch -------------------------------------------------------------

async def run_all(only_agent: str | None = None,
                  only_target: str | None = None) -> list[CaseResult]:
    cases = sorted(EVALS_DIR.glob("*.yaml"))
    parsed = [(p, yaml.safe_load(p.read_text())) for p in cases]

    if only_target:
        parsed = [(p, c) for p, c in parsed
                  if c.get("target", "agent") == only_target]
    if only_agent:
        parsed = [(p, c) for p, c in parsed
                  if c.get("agent") == only_agent]

    results: list[CaseResult] = []
    for path, _case in parsed:
        results.append(await run_case(path))
    return results


def write_report(results: list[CaseResult], out_path: Path) -> None:
    payload = {
        "ts": time.time(),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "cases": [
            {
                "name": r.name, "agent": r.agent, "target": r.target,
                "passed": r.passed, "duration_s": round(r.duration_s, 4),
                "pass_count": r.pass_count, "fail_count": r.fail_count,
                "failures": r.failures, "agent_error": r.agent_error,
            }
            for r in results
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str))


def run_all_sync(only_agent: str | None = None,
                 only_target: str | None = None) -> list[CaseResult]:
    return asyncio.run(run_all(only_agent=only_agent, only_target=only_target))
