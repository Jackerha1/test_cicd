from src.agents.base import BaseAgent
from src.context.builder import ContextBundle


class SecurityScanAgent(BaseAgent):
    name = "security_scan"
    output_key = "security_scan"

    def build_user_prompt(self, ctx: ContextBundle) -> str:
        return (
            "Scan the candidate patch (and any new dependencies it introduces) for security risk. "
            "Flag OWASP Top 10 patterns, secrets, weakened security controls, risky new dependencies. "
            "Set highest_severity to the worst of any finding (or 'none' if no findings)."
        )

    def post_validate(self, output: dict, ctx: ContextBundle):
        findings = output.get("findings", [])
        sev_rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        if findings:
            top = max(findings, key=lambda f: sev_rank.get(f.get("severity", "info"), 0))
            declared = output.get("highest_severity", "none")
            if declared in sev_rank and sev_rank[declared] < sev_rank.get(top["severity"], 0):
                return (
                    f"highest_severity={declared!r} contradicts findings (worst={top['severity']!r})"
                )
            if sev_rank.get(top["severity"], 0) >= 3 and output.get("recommendation") == "allow":
                return "found a high/critical issue but recommendation=allow — must be 'block'"
        else:
            if output.get("highest_severity") not in (None, "none"):
                return "no findings but highest_severity != 'none'"
        return None
