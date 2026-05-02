from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class DeploymentAgent(BaseAgent):
    name = "deployment"
    output_key = "deployment"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "Plan and report a staged rollout for the validated artifact: "
            "staging -> canary -> full. If any stage's metrics are unhealthy, set "
            "final_status='rolled_back' and incident=true. The orchestrator will execute the "
            "actual tool calls through the Tool Proxy — your output is the rollout plan + report."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        validation = ctx.prior_outputs.get("validation") or {}
        if validation.get("verdict") != "approve":
            return f"deployment cannot proceed: validation verdict={validation.get('verdict')!r}"

        stages = output.get("stages", [])
        names = [s.get("name") for s in stages]
        if output.get("target") == "production":
            if "staging" not in names:
                return "production deploy missing 'staging' stage in plan"
            if "canary" not in names:
                return "production deploy missing 'canary' stage in plan"
        return None
