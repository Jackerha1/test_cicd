"""Tool Proxy.

EVERY action an agent (or the orchestrator) takes against the outside world
goes through here. The proxy:
  1. Asks the Policy Engine if this (agent, action, risk_level) is allowed.
  2. If "needs_approval" → defers to the Approval Gate.
  3. If "forbidden" → denies and audits.
  4. If allowed → dispatches to the underlying tool implementation and audits.

Agents themselves never touch git, the filesystem outside the workspace, or
the network directly. That's the whole point.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.approval.gate import request_approval
from src.audit import log as audit
from src.policy_engine.engine import ActionDecision, authorize
from src.tool_proxy import tools


@dataclass
class ToolResult:
    ok: bool
    action: str
    decision: str                    # "auto" | "needs_approval" | "forbidden" | "denied_by_human"
    output: Any = None
    error: str | None = None


# Map of action name -> implementation function.
# Each implementation receives `(pipeline_id, **params)` and returns Any.
_TOOL_IMPL: dict[str, Callable] = {
    "create_branch":     tools.create_branch,
    "write_file":        tools.write_file,
    "commit":            tools.commit,
    "push_branch":       tools.push_branch,
    "open_pr":           tools.open_pr,
    "comment_pr":        tools.comment_pr,
    "merge_pr":          tools.merge_pr,
    "deploy_staging":    tools.deploy_staging,
    "deploy_canary":     tools.deploy_canary,
    "deploy_production": tools.deploy_production,
    "rollback":          tools.rollback,
}


def call(
    *,
    pipeline_id: str,
    agent: str,
    action: str,
    risk_level: str,
    params: dict | None = None,
) -> ToolResult:
    params = params or {}
    decision = authorize(agent, action, risk_level)

    audit.log(
        pipeline_id=pipeline_id,
        actor="tool_proxy",
        action=f"authorize:{action}",
        target=agent,
        risk_level=risk_level,
        decision=decision,
        payload={"params": params},
    )

    if decision == ActionDecision.FORBIDDEN:
        return ToolResult(ok=False, action=action, decision=decision,
                          error=f"agent={agent} not permitted to perform {action} at risk={risk_level}")

    if decision == ActionDecision.APPROVAL:
        approved = request_approval(
            pipeline_id=pipeline_id,
            agent=agent,
            action=action,
            risk_level=risk_level,
            params=params,
        )
        if not approved:
            return ToolResult(ok=False, action=action, decision="denied_by_human",
                              error="human reviewer denied the action")

    impl = _TOOL_IMPL.get(action)
    if impl is None:
        return ToolResult(ok=False, action=action, decision=decision,
                          error=f"no implementation registered for action {action!r}")

    try:
        out = impl(pipeline_id=pipeline_id, **params)
    except Exception as exc:
        audit.log(
            pipeline_id=pipeline_id,
            actor="tool_proxy",
            action=f"execute:{action}",
            target=agent,
            decision="error",
            payload={"error": str(exc)},
        )
        return ToolResult(ok=False, action=action, decision=decision, error=str(exc))

    audit.log(
        pipeline_id=pipeline_id,
        actor="tool_proxy",
        action=f"execute:{action}",
        target=agent,
        risk_level=risk_level,
        decision="executed",
        payload={"result_preview": str(out)[:500]},
    )
    return ToolResult(ok=True, action=action, decision=decision, output=out)
