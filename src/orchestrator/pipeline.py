"""Orchestrator — drives the full pipeline.

Two flows are supported:

  1. PR Review flow  — when an event is a pull_request:
        Triage -> Context -> Policy -> SecurityScan -> CodeReview ->
        Validation -> comment_pr (always) + merge_pr (if approved + risk allows)

  2. Auto Bug Fix flow — when an event is an issue (bug):
        Triage -> Planner -> [BugFix, TestWriter, Documentation] -> TestRunner ->
        SecurityScan -> CodeReview -> Validation -> [optional human approval] ->
        push_branch + open_pr

The orchestrator NEVER calls a tool directly — every external action goes
through the Tool Proxy, which gates on the Policy Engine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.agents import (
    AgentResult, BugFixAgent, CodeReviewAgent, CriticAgent, DeploymentAgent,
    DocumentationAgent, PlannerAgent, ReflectorAgent, SecurityScanAgent,
    TestWriterAgent, TriageAgent, ValidationAgent,
)
from src.audit import log as audit
from src.auth.permission import check_event
from src.config import WORKSPACE_DIR
from src.context.builder import build as build_context
from src.memory import archivist
from src.orchestrator.kernel import Task, run_dag
from src.policy_engine.engine import classify as classify_risk
from src.runner.test_runner import run_tests
from src.tool_proxy import proxy
from src.trigger.webhook import Event

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    pipeline_id: str
    flow: str                        # "pr_review" | "auto_fix"
    final_status: str                # "approved" | "blocked" | "failed" | "needs_human"
    risk_level: str
    agent_results: dict[str, AgentResult] = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    summary: str = ""
    critic_scores: dict[str, dict] = field(default_factory=dict)
    reflector: dict | None = None
    cost_usd: float = 0.0
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pipeline_id":   self.pipeline_id,
            "flow":          self.flow,
            "final_status":  self.final_status,
            "risk_level":    self.risk_level,
            "agents":        {k: v.to_dict() for k, v in self.agent_results.items()},
            "tool_calls":    self.tool_calls,
            "summary":       self.summary,
            "critic_scores": self.critic_scores,
            "reflector":     self.reflector,
            "cost_usd":      round(self.cost_usd, 6),
            "duration_s":    round(self.duration_s, 3),
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_pipeline(event: Event) -> PipelineResult:
    """Pick a flow, run it, then run post-pipeline reflection + archive hooks."""
    import time as _t

    t_start = _t.time()
    auth = check_event(event)
    files = event.files_changed or []
    verdict = classify_risk(files, diff=event.diff, pipeline_id=event.pipeline_id)

    ctx = build_context(event, trusted=auth.trusted)
    ctx.policy_verdict = verdict.to_dict()

    audit.log(
        pipeline_id=event.pipeline_id,
        actor="orchestrator",
        action="pipeline_start",
        target=f"{event.kind}/{event.repo}",
        risk_level=verdict.risk_level,
        decision="info",
    )

    if verdict.block:
        result = PipelineResult(
            pipeline_id=event.pipeline_id, flow="blocked",
            final_status="blocked", risk_level=verdict.risk_level,
            summary=f"Blocked by policy rule {verdict.rule_id}: {verdict.reason}",
        )
    elif event.kind == "pull_request":
        result = await _pr_review_flow(event, ctx, verdict)
    elif event.kind == "issue":
        result = await _auto_fix_flow(event, ctx, verdict)
    elif event.kind == "comment":
        result = await _comment_flow(event, ctx, verdict)
    else:
        result = PipelineResult(
            pipeline_id=event.pipeline_id, flow="unknown",
            final_status="failed", risk_level=verdict.risk_level,
            summary=f"unsupported event kind: {event.kind}",
        )

    # ---- Karpathy v2 post-hooks: reflection + archive + cost rollup ----

    result.duration_s = _t.time() - t_start
    result.cost_usd = sum(
        (ar.telemetry or {}).get("cost_usd", 0.0)
        for ar in result.agent_results.values()
    )

    if result.final_status in {"blocked", "failed"} and result.agent_results:
        try:
            reflector = await ReflectorAgent().run(ctx)
            if reflector.ok:
                result.reflector = reflector.output
                if reflector.telemetry:
                    result.cost_usd += reflector.telemetry.get("cost_usd", 0.0)
                audit.log(
                    pipeline_id=event.pipeline_id, actor="reflector",
                    action="root_cause", decision="info",
                    payload=reflector.output,
                )
        except Exception as exc:
            logger.warning("reflector failed: %s", exc)

    try:
        archivist.archive(
            pipeline_id=event.pipeline_id,
            repo=event.repo,
            event_title=event.title or event.kind,
            final_status=result.final_status,
            files_changed=event.files_changed or [],
            summary=(result.summary or "")[:500],
            reflector_root_cause=(result.reflector or {}).get("root_cause"),
        )
    except Exception as exc:
        logger.warning("archivist failed: %s", exc)

    # Data flywheel: persist the (event, outcome) example.
    try:
        from src.audit.dataset import write_run
        write_run(pipeline_id=event.pipeline_id,
                  event=event.dict(), result=result.to_dict())
    except Exception as exc:
        logger.warning("dataset writer failed: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Flow 1 — PR Review
# ---------------------------------------------------------------------------

async def _pr_review_flow(event: Event, ctx, verdict) -> PipelineResult:
    result = PipelineResult(pipeline_id=event.pipeline_id, flow="pr_review",
                            final_status="failed", risk_level=verdict.risk_level)

    # 1. Triage
    triage = await TriageAgent().run(ctx)
    result.agent_results["triage"] = triage
    if not triage.ok:
        result.summary = f"triage failed: {triage.error}"
        return result
    ctx.add_output("triage", triage.output)

    # 2 + 3. Security scan + Code review run in PARALLEL (LLM-OS kernel).
    sec_agent = SecurityScanAgent()
    rev_agent = CodeReviewAgent()
    dag = await run_dag([
        Task(name="security_scan", fn=lambda: sec_agent.run(ctx)),
        Task(name="code_review",   fn=lambda: rev_agent.run(ctx)),
    ], pipeline_id=event.pipeline_id)
    sec    = dag["security_scan"]
    review = dag["code_review"]
    result.agent_results["security_scan"] = sec
    result.agent_results["code_review"]   = review
    if sec.ok:
        ctx.add_output("security_scan", sec.output)
    if review.ok:
        ctx.add_output("code_review", review.output)

    # 4. Validation (sequential — needs both prior outputs).
    validation = await ValidationAgent().run(ctx)
    result.agent_results["validation"] = validation
    if validation.ok:
        ctx.add_output("validation", validation.output)

    # 5. Critic grades the Validation verdict (independent LLM-as-judge).
    if validation.ok:
        critic = await CriticAgent(target_agent="validation").run(ctx)
        result.agent_results["critic_validation"] = critic
        if critic.ok:
            result.critic_scores["validation"] = critic.output

    # 6. Always post a comment with the review summary
    summary = _build_pr_comment(triage, sec, review, validation)
    comment = proxy.call(
        pipeline_id=event.pipeline_id, agent="orchestrator", action="comment_pr",
        risk_level=verdict.risk_level,
        params={"pr_number": event.number, "body": summary},
    )
    result.tool_calls.append({"action": "comment_pr", "ok": comment.ok, "decision": comment.decision})

    # 7. Decide final status
    v = (validation.output or {}).get("verdict") if validation.ok else "block"
    if v == "approve" and not verdict.require_human_approval:
        result.final_status = "approved"
    elif v == "approve" and verdict.require_human_approval:
        result.final_status = "needs_human"
    elif v == "request_changes":
        result.final_status = "needs_human"
    else:
        result.final_status = "blocked"

    result.summary = summary
    audit.log(
        pipeline_id=event.pipeline_id, actor="orchestrator",
        action="pipeline_done", risk_level=verdict.risk_level,
        decision=result.final_status,
    )
    return result


# ---------------------------------------------------------------------------
# Flow 2 — Auto Bug Fix
# ---------------------------------------------------------------------------

async def _auto_fix_flow(event: Event, ctx, verdict) -> PipelineResult:
    result = PipelineResult(pipeline_id=event.pipeline_id, flow="auto_fix",
                            final_status="failed", risk_level=verdict.risk_level)

    # 1. Triage
    triage = await TriageAgent().run(ctx)
    result.agent_results["triage"] = triage
    if not triage.ok:
        result.summary = f"triage failed: {triage.error}"
        return result
    ctx.add_output("triage", triage.output)

    # 2. Planner
    planner = await PlannerAgent().run(ctx)
    result.agent_results["planner"] = planner
    if not planner.ok:
        result.summary = f"planner failed: {planner.error}"
        return result
    ctx.add_output("planner", planner.output)

    # 3. Bug Fix
    bug_fix = await BugFixAgent().run(ctx)
    result.agent_results["bug_fix"] = bug_fix
    if not bug_fix.ok:
        result.summary = f"bug_fix failed: {bug_fix.error}"
        return result
    ctx.add_output("bug_fix", bug_fix.output)

    # 4. Test Writer
    tw = await TestWriterAgent().run(ctx)
    result.agent_results["test_writer"] = tw
    if not tw.ok:
        result.summary = f"test_writer failed: {tw.error}"
        return result
    ctx.add_output("test_writer", tw.output)

    # 5. Documentation (best-effort)
    docs = await DocumentationAgent().run(ctx)
    result.agent_results["documentation"] = docs
    if docs.ok:
        ctx.add_output("documentation", docs.output)

    # 6. Materialize patch + tests in workspace, run real test runner
    workdir = WORKSPACE_DIR / event.pipeline_id / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    _materialize(workdir, bug_fix.output, tw.output, docs.output if docs.ok else None)
    runner_out = await run_tests(pipeline_id=event.pipeline_id, workdir=workdir)
    ctx.add_output("test_runner", runner_out.to_dict())

    # 7. Security scan
    sec = await SecurityScanAgent().run(ctx)
    result.agent_results["security_scan"] = sec
    if sec.ok:
        ctx.add_output("security_scan", sec.output)

    # 8. Code review
    review = await CodeReviewAgent().run(ctx)
    result.agent_results["code_review"] = review
    if review.ok:
        ctx.add_output("code_review", review.output)

    # 9. Validation (final gate)
    validation = await ValidationAgent().run(ctx)
    result.agent_results["validation"] = validation
    if validation.ok:
        ctx.add_output("validation", validation.output)

    v = (validation.output or {}).get("verdict") if validation.ok else "block"
    if v != "approve":
        result.final_status = "blocked"
        result.summary = f"validation refused: {(validation.output or {}).get('failed_checks')}"
        return result

    # 10. Tool actions: branch + write files + commit + push + open PR
    branch = f"ai-cicd/fix-{event.pipeline_id}"
    proxy.call(pipeline_id=event.pipeline_id, agent="bug_fix", action="create_branch",
               risk_level=verdict.risk_level, params={"name": branch, "base": event.base_branch or "main"})

    for fc in bug_fix.output.get("files_changed", []):
        proxy.call(pipeline_id=event.pipeline_id, agent="bug_fix", action="write_file",
                   risk_level=verdict.risk_level,
                   params={"path": fc, "content": _file_from_patch(bug_fix.output["patch"], fc)})
    for t in tw.output.get("tests", []):
        proxy.call(pipeline_id=event.pipeline_id, agent="test_writer", action="write_file",
                   risk_level=verdict.risk_level,
                   params={"path": t["path"], "content": t["content"]})
    if docs.ok:
        for f in docs.output.get("files", []):
            proxy.call(pipeline_id=event.pipeline_id, agent="documentation", action="write_file",
                       risk_level=verdict.risk_level,
                       params={"path": f["path"], "content": f["content"]})

    proxy.call(pipeline_id=event.pipeline_id, agent="bug_fix", action="commit",
               risk_level=verdict.risk_level,
               params={"message": f"fix: {triage.output.get('summary', 'auto-fix')}",
                       "files": bug_fix.output.get("files_changed", [])})

    push = proxy.call(pipeline_id=event.pipeline_id, agent="orchestrator", action="push_branch",
                      risk_level=verdict.risk_level, params={"branch": branch})
    result.tool_calls.append({"action": "push_branch", "ok": push.ok, "decision": push.decision})

    pr = proxy.call(pipeline_id=event.pipeline_id, agent="orchestrator", action="open_pr",
                    risk_level=verdict.risk_level,
                    params={"title": f"[AI-CICD] {event.title}", "body": result.summary or "",
                            "branch": branch, "base": event.base_branch or "main"})
    result.tool_calls.append({"action": "open_pr", "ok": pr.ok, "decision": pr.decision})

    if pr.ok:
        result.final_status = "approved" if not verdict.require_human_approval else "needs_human"
        result.summary = f"PR opened: {pr.output.get('url') if pr.output else '(simulated)'}"
    else:
        result.final_status = "needs_human"
        result.summary = f"open_pr deferred to human: {pr.error or pr.decision}"

    audit.log(pipeline_id=event.pipeline_id, actor="orchestrator", action="pipeline_done",
              risk_level=verdict.risk_level, decision=result.final_status)
    return result


# ---------------------------------------------------------------------------
# Flow 3 — Comment commands (e.g. "/ai fix")
# ---------------------------------------------------------------------------

async def _comment_flow(event: Event, ctx, verdict) -> PipelineResult:
    body = (event.body or "").lower().strip()
    if "/ai fix" in body:
        synthetic = event.copy(update={"kind": "issue", "action": "opened"})
        return await _auto_fix_flow(synthetic, ctx, verdict)
    if "/ai review" in body:
        synthetic = event.copy(update={"kind": "pull_request", "action": "opened"})
        return await _pr_review_flow(synthetic, ctx, verdict)
    return PipelineResult(
        pipeline_id=event.pipeline_id, flow="comment",
        final_status="failed", risk_level=verdict.risk_level,
        summary="comment did not contain a recognized command (/ai fix | /ai review)",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_pr_comment(triage: AgentResult, sec: AgentResult, review: AgentResult,
                      validation: AgentResult) -> str:
    parts = ["## AI-CICD review", ""]
    if triage.ok:
        t = triage.output
        parts.append(f"**Triage**: kind={t.get('kind')}, severity={t.get('severity')}, scope={t.get('scope')}")
        if t.get("prompt_injection_suspected"):
            parts.append("> ⚠ prompt-injection suspected in event body")
    if sec.ok:
        s = sec.output
        parts.append(f"**Security**: highest_severity={s.get('highest_severity')}, "
                     f"recommendation={s.get('recommendation')} ({len(s.get('findings', []))} findings)")
    if review.ok:
        r = review.output
        parts.append(f"**Code review**: recommendation={r.get('recommendation')} "
                     f"({len(r.get('issues', []))} comments)")
    if validation.ok:
        v = validation.output
        parts.append(f"**Validation**: verdict=**{v.get('verdict')}**")
        if v.get("failed_checks"):
            parts.append("Failed checks:")
            for fc in v["failed_checks"]:
                parts.append(f"- {fc}")
    return "\n".join(parts)


def _materialize(workdir, bug_fix: dict, tw: dict, docs: dict | None) -> None:
    """Drop generated files into the workspace so the test runner has something real."""
    from pathlib import Path as _P
    files = {}
    for t in tw.get("tests", []):
        files[t["path"]] = t["content"]
    if docs:
        for f in docs.get("files", []):
            files[f["path"]] = f["content"]
    for path, content in files.items():
        target = workdir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    # Bug-fix patch is left as-is in audit (applying real diffs is out of MVP scope).
    (workdir / "PATCH.diff").write_text(bug_fix.get("patch", ""))


def _file_from_patch(patch: str, path: str) -> str:
    """Stub: real impl would parse the unified diff and produce the post-image.

    For the MVP we just attach the patch text — the simulated tools layer
    records intent rather than applying real diffs.
    """
    return f"# === Patch slice for {path} ===\n{patch}\n"
