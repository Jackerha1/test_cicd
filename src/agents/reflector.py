"""Reflector — runs after a blocked/failed pipeline to root-cause."""
from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class ReflectorAgent(BaseAgent):
    name = "reflector"
    output_key = "reflector"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "The pipeline finished with a non-success status. Read every prior agent's output "
            "and the policy verdict in your context. Pick ONE primary root cause from the rubric "
            "in your system prompt and propose ONE concrete fix (prompt/policy/schema edit)."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        fix = output.get("suggested_fix") or {}
        target = fix.get("target", "")
        kind = fix.get("kind")
        if kind == "prompt_edit" and not target.startswith("prompts/"):
            return f"prompt_edit target must start with 'prompts/': got {target!r}"
        if kind == "policy_edit" and not target.startswith("policies/"):
            return f"policy_edit target must start with 'policies/': got {target!r}"
        if kind == "schema_edit" and not target.startswith("schemas/"):
            return f"schema_edit target must start with 'schemas/': got {target!r}"
        return None
