import fnmatch

from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class ValidationAgent(BaseAgent):
    """Final cross-check before any artifact leaves the pipeline.

    The model produces a verdict, but the post_validate hook here ALSO
    enforces hard rules deterministically — a misbehaving model can't
    talk its way to 'approve' if any objective check fails.
    """
    name = "validation"
    output_key = "validation"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "You are the final gate. Cross-check every prior agent's output against the rules in "
            "your system prompt. List EACH check you ran in `checks[]` with pass/fail. "
            "Set `verdict` to approve / request_changes / block based on the strictest failing check."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        verdict = output.get("verdict")
        failures: list[str] = list(output.get("failed_checks") or [])

        # ---- Hard objective checks the model cannot override ----

        bug = ctx.prior_outputs.get("bug_fix")
        plan = ctx.prior_outputs.get("planner") or {}
        sec = ctx.prior_outputs.get("security_scan") or {}
        rev = ctx.prior_outputs.get("code_review") or {}
        runner = ctx.prior_outputs.get("test_runner")

        if bug:
            if bug.get("confidence") == "low":
                failures.append("bug_fix.confidence=low")
            allowed = plan.get("allowed_paths", [])
            files = bug.get("files_changed", [])
            outside = [f for f in files
                       if allowed and not any(fnmatch.fnmatch(f, p) for p in allowed)]
            if outside:
                failures.append(f"patch_outside_allowed_paths: {outside}")

        if sec.get("highest_severity") in {"high", "critical"}:
            failures.append(f"security_scan.highest_severity={sec.get('highest_severity')}")
        if sec.get("recommendation") == "block":
            failures.append("security_scan.recommendation=block")

        if rev.get("recommendation") in {"request_changes", "block"}:
            failures.append(f"code_review.recommendation={rev.get('recommendation')}")

        if runner is not None:
            if runner.get("status") != "pass":
                failures.append(f"test_runner.status={runner.get('status')}")
            if runner.get("synthetic"):
                failures.append("test_runner.synthetic=true (no real tests ran)")

        if failures and verdict == "approve":
            return f"validation said 'approve' but hard checks failed: {failures}"

        # Mutate output in place so the orchestrator sees the merged failure list.
        output["failed_checks"] = list(dict.fromkeys(failures))  # de-dup, preserve order
        return None
