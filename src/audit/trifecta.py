"""Lethal Trifecta auditor.

Karpathy (and Simon Willison) framing: an AI agent becomes dangerous when it
holds ALL THREE of:

    1. access to UNTRUSTED INPUT (issue/PR body, web fetch, etc.)
    2. access to PRIVATE DATA (secrets, prod DB, customer data)
    3. ability to EXFILTRATE  (post comments, push branches, deploy)

This module statically analyzes the approval matrix and computes which
agents fall into each leg. If any agent has all three, that's a hard fail —
the system should refuse to start.

Run via `ai-cicd trifecta-audit`.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from src.config import POLICIES_DIR

# Capabilities that count as "exfiltration" — observable outside the sandbox.
_EXFIL_ACTIONS = {
    "comment_pr", "open_pr", "push_branch", "merge_pr",
    "deploy_staging", "deploy_canary", "deploy_production",
}

# Agents that consume UNTRUSTED input (issue body, PR description, comments).
# Computed by inspection of which agents read `event.body` or `event.diff`.
_UNTRUSTED_INPUT_AGENTS = {
    "triage",          # reads event body to classify
    "planner",         # reads triage + event
    "bug_fix",         # reads issue body
    "test_writer",     # reads bug_fix output (which derived from issue)
    "security_scan",   # reads diff
    "code_review",     # reads diff
    "documentation",   # reads patch summary
    "validation",      # reads everything
    "deployment",      # reads validation output (already laundered)
}

# Agents that have access to PRIVATE DATA. Today: nobody, by design —
# secrets are blocked at policy + redacted in context.
_PRIVATE_DATA_AGENTS: set[str] = set()


@dataclass
class TrifectaFinding:
    agent: str
    has_untrusted_input: bool
    has_private_data:    bool
    can_exfiltrate:      bool
    legs:                int

    @property
    def lethal(self) -> bool:
        return self.legs == 3

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "has_untrusted_input": self.has_untrusted_input,
            "has_private_data":    self.has_private_data,
            "can_exfiltrate":      self.can_exfiltrate,
            "legs":                self.legs,
            "lethal":              self.lethal,
        }


def audit_trifecta() -> list[TrifectaFinding]:
    """Inspect the approval matrix and return per-agent trifecta legs."""
    cfg = yaml.safe_load((POLICIES_DIR / "approval_matrix.yaml").read_text()) or {}
    caps = cfg.get("agent_capabilities", {})
    out: list[TrifectaFinding] = []
    for agent, actions in caps.items():
        actions_set = set(actions or [])
        ui = agent in _UNTRUSTED_INPUT_AGENTS
        pd = agent in _PRIVATE_DATA_AGENTS
        exf = bool(actions_set & _EXFIL_ACTIONS)
        legs = int(ui) + int(pd) + int(exf)
        out.append(TrifectaFinding(agent=agent, has_untrusted_input=ui,
                                   has_private_data=pd, can_exfiltrate=exf, legs=legs))
    return out


def lethal_findings() -> list[TrifectaFinding]:
    return [f for f in audit_trifecta() if f.lethal]
