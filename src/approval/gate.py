"""Human Approval Gate.

For the MVP this is a CLI prompt. In production, replace with a Slack
button, GitHub PR review, or PagerDuty incident workflow — same signature.

The gate ALWAYS audits both the request and the human decision so we can
later answer "who approved this deploy and when?".
"""
from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel

from src.audit import log as audit
from src.config import AUTO_APPROVE

_console = Console()


def request_approval(
    *,
    pipeline_id: str,
    agent: str,
    action: str,
    risk_level: str,
    params: dict | None = None,
) -> bool:
    """Block until a human approves or rejects. Returns True if approved."""
    audit.log(
        pipeline_id=pipeline_id,
        actor="approval_gate",
        action="approval_requested",
        target=action,
        risk_level=risk_level,
        decision="pending",
        payload={"agent": agent, "params": params},
    )

    if AUTO_APPROVE:
        audit.log(
            pipeline_id=pipeline_id,
            actor="approval_gate",
            action="approval_decision",
            target=action,
            risk_level=risk_level,
            decision="approved",
            payload={"by": "auto", "warning": "AUTO_APPROVE=true"},
        )
        _console.print(f"[yellow]AUTO-APPROVED[/] {agent} → {action} (risk={risk_level})")
        return True

    if not sys.stdin.isatty():
        # Non-interactive run (CI / pipe). Default to deny — never auto-allow on rails.
        audit.log(
            pipeline_id=pipeline_id,
            actor="approval_gate",
            action="approval_decision",
            target=action,
            risk_level=risk_level,
            decision="denied",
            payload={"by": "non_interactive_default"},
        )
        return False

    _console.print(Panel.fit(
        f"[bold]Action requires human approval[/]\n"
        f"  agent      : {agent}\n"
        f"  action     : {action}\n"
        f"  risk_level : {risk_level}\n"
        f"  params     : {params or '{}'}",
        title=f"Pipeline {pipeline_id}",
        border_style="yellow",
    ))
    answer = ""
    while answer not in {"y", "yes", "n", "no"}:
        try:
            answer = input("Approve? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer == "":
            answer = "n"

    approved = answer in {"y", "yes"}
    audit.log(
        pipeline_id=pipeline_id,
        actor="approval_gate",
        action="approval_decision",
        target=action,
        risk_level=risk_level,
        decision="approved" if approved else "denied",
        payload={"by": "human"},
    )
    return approved
