#!/usr/bin/env python3
"""GitHub PR webhook payload → normalized AI-CICD Event JSON (stdout).

Used by .github/workflows/dogfood-pr-review.yml to bridge GitHub's PR shape
into what the pipeline consumes. Reads $GITHUB_EVENT_PATH (the webhook
payload Actions writes to disk) and shells out to `gh` for the diff +
file list (those aren't in the webhook body).

Karpathy: keep adapters tiny and side-effect-free. This script does one
thing: read GitHub, emit normalized JSON. Don't extend it with policy
decisions — that's the pipeline's job.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _gh_text(*args: str) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args)} failed: {res.stderr}\n")
        sys.exit(2)
    return res.stdout


def _gh_json(*args: str):
    return json.loads(_gh_text(*args) or "{}")


def main() -> None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        sys.stderr.write("GITHUB_EVENT_PATH not set or missing — not in Actions?\n")
        sys.exit(2)

    payload = json.loads(Path(event_path).read_text())
    pr = payload.get("pull_request") or {}
    if not pr:
        sys.stderr.write("not a pull_request event\n")
        sys.exit(2)

    repo = payload["repository"]["full_name"]
    number = pr["number"]

    # Diff: webhook doesn't include it. `gh pr diff` returns the unified diff.
    diff = _gh_text("pr", "diff", str(number), "-R", repo)

    # File list (richer than what's on the webhook for synchronize events).
    files_info = _gh_json("pr", "view", str(number), "-R", repo, "--json", "files")
    files_changed = [f["path"] for f in (files_info.get("files") or [])]

    # Truncate diff if huge — Context Builder caps it anyway, but be defensive.
    MAX_DIFF = 60_000
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + f"\n... [truncated {len(diff) - MAX_DIFF} chars]"

    event = {
        "kind":          "pull_request",
        "action":        payload.get("action", "opened"),
        "repo":          repo,
        "number":        number,
        "title":         pr.get("title", ""),
        "body":          pr.get("body") or "",
        "author":        (pr.get("user") or {}).get("login", "unknown"),
        "branch":        (pr.get("head") or {}).get("ref", ""),
        "base_branch":   (pr.get("base") or {}).get("ref", "main"),
        "files_changed": files_changed,
        "diff":          diff,
        "labels":        [l["name"] for l in (pr.get("labels") or [])],
    }
    json.dump(event, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
