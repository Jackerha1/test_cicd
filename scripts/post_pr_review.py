#!/usr/bin/env python3
"""Post the latest pipeline result as a PR comment.

Update-not-stack: if a previous AI-CICD comment exists (we tag it with a
hidden HTML marker), edit it instead of adding a new one. Karpathy: don't
spam the reviewer's notifications on every push.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MARKER = "<!-- ai-cicd-review -->"

ICONS = {
    "approved":    "✅",
    "needs_human": "⚠️",
    "blocked":     "🚫",
    "failed":      "❌",
}


# ---------------------------------------------------------------------------

def _latest_result() -> dict | None:
    logs = Path("logs")
    files = sorted(logs.glob("pipe-*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text())


def _gh(*args: str, body: str | None = None) -> str:
    cmd = ["gh", *args]
    res = subprocess.run(cmd, input=body, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args)} failed: {res.stderr}\n")
        sys.exit(2)
    return res.stdout


def _find_existing_comment(repo: str, pr: int) -> int | None:
    # --paginate walks all comment pages so the marker is found on
    # long-discussion PRs (default GitHub page size is 30).
    # Addresses code_review feedback on PR #1 (pipe-298721cf).
    raw = _gh("api", "--paginate", f"repos/{repo}/issues/{pr}/comments")
    # `gh --paginate` concatenates JSON arrays — split on `][`.
    rows: list = []
    for chunk in raw.replace("][", "]<<>>[").split("<<>>"):
        if chunk.strip():
            rows.extend(json.loads(chunk))
    for c in rows:
        if MARKER in (c.get("body") or ""):
            return c["id"]
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(result: dict) -> str:
    status = result.get("final_status", "unknown")
    icon = ICONS.get(status, "❔")
    flow = result.get("flow", "?")
    risk = result.get("risk_level", "?")
    cost = float(result.get("cost_usd") or 0.0)
    dur = float(result.get("duration_s") or 0.0)
    pid = result.get("pipeline_id", "?")

    out = [
        MARKER,
        f"## {icon} AI-CICD review — `{status}`",
        "",
        f"**Flow** `{flow}` · **Risk** `{risk}` · **Cost** `${cost:.4f}` · **Duration** `{dur:.1f}s`",
        "",
        result.get("summary", "") or "_(no summary)_",
        "",
        "### Per-agent",
        "",
    ]
    for name, ar in (result.get("agents") or {}).items():
        ok = "✓" if ar.get("ok") else "✗"
        prov = (ar.get("provider") or "?")
        retries = f" *(retries={ar['retries']})*" if ar.get("retries") else ""
        err = f" — `{ar['error'][:80]}`" if ar.get("error") else ""
        out.append(f"- {ok} **{name}** *(via {prov})*{retries}{err}")

    refl = result.get("reflector")
    if refl:
        fix = refl.get("suggested_fix") or {}
        out += [
            "",
            "### Reflector root-cause",
            f"- **{refl.get('root_cause', '?')}** — {(refl.get('summary') or '')[:300]}",
        ]
        if fix:
            out.append(
                f"- **Suggested fix**: `{fix.get('kind')}` on "
                f"`{fix.get('target')}` — {(fix.get('description') or '')[:300]}"
            )

    critic = result.get("critic_scores") or {}
    if critic:
        out += ["", "### Critic scores"]
        for target, c in critic.items():
            score = c.get("score_overall", "?")
            out.append(f"- {target}: **{score}/10** — {(c.get('reasoning') or '')[:200]}")

    tools = result.get("tool_calls") or []
    if tools:
        out += ["", "### Tool calls"]
        for tc in tools:
            ok = "✓" if tc.get("ok") else "✗"
            out.append(
                f"- {ok} `{tc.get('action')}` *(decision: {tc.get('decision')})*"
                + (f" — {tc.get('error')}" if tc.get("error") else "")
            )

    out += ["", f"_Pipeline `{pid}` · post-mortem with `make audit PIPELINE_ID={pid}`_"]
    return "\n".join(out)


# ---------------------------------------------------------------------------

def main() -> None:
    result = _latest_result()
    if not result:
        sys.stderr.write("no pipeline result file found in logs/pipe-*.json\n")
        sys.exit(1)

    body = _render(result)

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        sys.stderr.write("GITHUB_EVENT_PATH not set — printing body to stdout instead.\n")
        sys.stdout.write(body + "\n")
        return

    payload = json.loads(Path(event_path).read_text())
    repo = payload["repository"]["full_name"]
    pr = payload["pull_request"]["number"]

    existing = _find_existing_comment(repo, pr)
    if existing:
        # Edit-in-place via the issues API (PATCH).
        _gh("api", "-X", "PATCH",
            f"repos/{repo}/issues/comments/{existing}",
            "-f", f"body={body}")
        sys.stderr.write(f"updated existing comment {existing}\n")
    else:
        _gh("pr", "comment", str(pr), "-R", repo, "--body", body)
        sys.stderr.write("posted new comment\n")


if __name__ == "__main__":
    main()
