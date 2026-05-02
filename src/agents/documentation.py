from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class DocumentationAgent(BaseAgent):
    name = "documentation"
    output_key = "documentation"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "If the patch in context is user-visible (changed API, behavior, or config), "
            "produce updated docs (README/CHANGELOG/docs/*). If it's purely internal, "
            "return an empty files list and explain in summary."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        for f in output.get("files", []):
            path = f.get("path", "")
            if not (path.endswith(".md") or path.startswith("docs/")
                    or path.endswith("CHANGELOG") or path == "README.md"):
                return f"documentation tried to write a non-doc file: {path!r}"
        return None
