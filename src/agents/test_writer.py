import re

from src.agents.base import BaseAgent
from src.context.builder import ContextBundle

# Smell patterns that indicate an empty/useless test.
_BAD_ASSERT = re.compile(r"\bassert\s+(True|true|1\s*==\s*1|1)\s*$", re.MULTILINE)


class TestWriterAgent(BaseAgent):
    name = "test_writer"
    output_key = "test_writer"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        bug = ctx.prior_outputs.get("bug_fix", {})
        return (
            "Write tests that would FAIL if the bug were re-introduced. "
            "Use the bug_fix patch in context to know what behavior to verify. "
            f"Patch summary: {bug.get('summary', 'n/a')}"
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        tests = output.get("tests", [])
        if not tests:
            return "test_writer produced zero tests"
        for t in tests:
            content = t.get("content", "")
            if "assert" not in content and "expect(" not in content and "test(" not in content:
                return f"test {t.get('path')!r} contains no assertion / expect call"
            if _BAD_ASSERT.search(content):
                return f"test {t.get('path')!r} uses a meaningless assertion (assert True / 1==1)"
        return None
