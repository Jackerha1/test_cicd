import fnmatch

from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class BugFixAgent(BaseAgent):
    name = "bug_fix"
    output_key = "bug_fix"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        plan = ctx.prior_outputs.get("planner", {})
        allowed = plan.get("allowed_paths", [])
        return (
            "Produce the smallest unified-diff patch that resolves the bug described above.\n"
            f"You may ONLY touch files matching these globs: {allowed or '(none — refuse)'}\n"
            "If you cannot fix the bug from what's in context, return confidence='low' and "
            "explain what info is missing in summary. Do NOT guess wildly."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        plan = ctx.prior_outputs.get("planner", {})
        allowed = plan.get("allowed_paths", [])
        files = output.get("files_changed", [])
        if not files:
            return "bug_fix produced an empty files_changed list"
        if allowed:
            bad = [f for f in files if not any(fnmatch.fnmatch(f, p) for p in allowed)]
            if bad:
                return f"bug_fix touched files outside allowed_paths: {bad}"
        if "patch" not in output or not output["patch"].strip():
            return "bug_fix returned an empty patch"
        return None
