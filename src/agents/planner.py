from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class PlannerAgent(BaseAgent):
    name = "planner"
    output_key = "planner"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        triage = ctx.prior_outputs.get("triage", {})
        kind = triage.get("kind", "unknown")
        return (
            f"Plan the work to handle this {kind}. Decompose into tasks and assign each to "
            "exactly one specialist agent. Set allowed_paths conservatively — patches outside "
            "this list will be rejected. Be strict about scope."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        # A plan with zero tasks is meaningless.
        if not output.get("tasks"):
            return "planner returned no tasks"
        # allowed_paths must be non-empty for any plan that includes a code-modifying agent.
        modifying = {"bug_fix", "test_writer", "documentation"}
        if any(t.get("agent") in modifying for t in output["tasks"]) and not output.get("allowed_paths"):
            return "planner included a code-modifying task but allowed_paths is empty"
        return None
