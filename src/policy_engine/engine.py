"""Policy Engine — DETERMINISTIC.

This is intentionally NOT an LLM. Policy rules are loaded from YAML and
evaluated with plain glob matching. Putting AI here would defeat the
purpose: the engine is the deterministic backstop that AI can't talk
its way around.

Two surfaces:
  - classify(files_changed) → risk level + approval requirements
  - allowed(agent, action, risk_level) → bool / "needs_approval" / "forbidden"
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from src.audit import log as audit
from src.config import POLICIES_DIR


@dataclass
class PolicyVerdict:
    risk_level: str                       # low | medium | high | critical
    require_human_approval: bool
    block: bool
    rule_id: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "require_human_approval": self.require_human_approval,
            "block": self.block,
            "rule_id": self.rule_id,
            "reason": self.reason,
        }


def _load_yaml(name: str) -> dict:
    p = POLICIES_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Missing policy file: {p}")
    return yaml.safe_load(p.read_text()) or {}


def classify(files_changed: list[str], *, pipeline_id: str = "n/a") -> PolicyVerdict:
    """Return the strictest verdict matching any changed file."""
    cfg = _load_yaml("risk_rules.yaml")
    rules = cfg.get("rules", [])
    severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    best: Optional[PolicyVerdict] = None
    for f in files_changed:
        for rule in rules:
            patterns = rule.get("match", {}).get("paths", [])
            if any(fnmatch.fnmatch(f, pat) for pat in patterns):
                v = PolicyVerdict(
                    risk_level=rule["risk_level"],
                    require_human_approval=bool(rule.get("require_human_approval", False)),
                    block=bool(rule.get("block", False)),
                    rule_id=rule["id"],
                    reason=rule.get("reason", ""),
                )
                if best is None or severity_rank[v.risk_level] > severity_rank[best.risk_level]:
                    best = v
                break  # first match wins per file

    if best is None:
        d = cfg.get("default", {})
        best = PolicyVerdict(
            risk_level=d.get("risk_level", "medium"),
            require_human_approval=bool(d.get("require_human_approval", False)),
            block=False,
            rule_id="default",
            reason=d.get("reason", "no rule matched"),
        )

    audit.log(
        pipeline_id=pipeline_id,
        actor="policy_engine",
        action="classify",
        risk_level=best.risk_level,
        decision="blocked" if best.block else ("review" if best.require_human_approval else "allowed"),
        payload=best.to_dict(),
    )
    return best


# ---------------------------------------------------------------------------
# Action authorization (used by the Tool Proxy)
# ---------------------------------------------------------------------------

class ActionDecision:
    AUTO = "auto"
    APPROVAL = "needs_approval"
    FORBIDDEN = "forbidden"


def authorize(agent: str, action: str, risk_level: str) -> str:
    """Decide whether `agent` may perform `action` at the given `risk_level`.

    Returns one of: "auto" | "needs_approval" | "forbidden".
    """
    cfg = _load_yaml("approval_matrix.yaml")
    risk_actions = cfg.get("risk_actions", {}).get(risk_level, {})
    agent_caps = set(cfg.get("agent_capabilities", {}).get(agent, []))

    # First gate: agent capability ceiling.
    if action not in agent_caps:
        return ActionDecision.FORBIDDEN

    # Second gate: risk-level table.
    if action in risk_actions.get("forbidden", []):
        return ActionDecision.FORBIDDEN
    if action in risk_actions.get("require_approval", []):
        return ActionDecision.APPROVAL
    if action in risk_actions.get("auto", []):
        return ActionDecision.AUTO
    # If risk table doesn't mention it, default to needing approval.
    return ActionDecision.APPROVAL
