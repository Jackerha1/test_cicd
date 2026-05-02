from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class CodeReviewAgent(BaseAgent):
    name = "code_review"
    output_key = "code_review"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "Review the patch in context. Focus on logic, edge cases, scope creep, "
            "test coverage of the regression, and convention drift. Use the security report "
            "in context to factor in any flagged issues. Recommend approve / request_changes / block."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        sec = ctx.prior_outputs.get("security_scan", {})
        rec = output.get("recommendation")
        if sec.get("highest_severity") in {"high", "critical"} and rec == "approve":
            return "code_review approved despite high/critical security finding"

        runner = ctx.prior_outputs.get("test_runner", {})
        if runner and runner.get("status") == "fail" and rec == "approve":
            return "code_review approved despite failing tests"

        # Blocker issue listed but recommendation says approve → contradiction.
        if any(i.get("severity") == "blocker" for i in output.get("issues", [])) and rec == "approve":
            return "code_review listed a blocker issue but recommendation=approve"
        return None
