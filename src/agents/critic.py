"""Critic agent — independent LLM-as-judge that grades any prior agent's output."""
from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class CriticAgent(BaseAgent):
    name = "critic"
    output_key = "critic"

    def __init__(self, target_agent: str):
        super().__init__()
        self.target_agent = target_agent

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        target_out = ctx.prior_outputs.get(self.target_agent)
        if target_out is None:
            return f"No output for agent {self.target_agent!r} is in your context. Set score_overall=-1."
        return (
            f"Grade the upstream agent {self.target_agent!r}. Its output is in your context. "
            "Compare against the original event and any policy verdict. "
            f"Set target_agent={self.target_agent!r} in your reply. "
            "Sub-scores must justify the overall score."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        if output.get("target_agent") != self.target_agent:
            return f"target_agent in reply ({output.get('target_agent')!r}) != requested ({self.target_agent!r})"
        sub = output.get("subscores") or {}
        overall = output.get("score_overall", -1)
        if overall >= 0 and sub:
            mean = sum(sub.values()) / max(1, len(sub))
            if abs(mean - overall) > 1.5:
                return f"score_overall={overall} diverges from sub-score mean={mean:.2f} by >1.5"
        return None
