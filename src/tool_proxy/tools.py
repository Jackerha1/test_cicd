"""Concrete tool implementations called by the Tool Proxy.

For the MVP these are SAFE simulations: they write to the workspace dir,
log to audit, and never reach a real GitHub or production server.
That's deliberate — we want to demo the full flow on a single laptop.

Swap each function for a real `gh` / `kubectl` / cloud-deploy call to
turn this into production. The Tool Proxy will still gate every call.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.config import WORKSPACE_DIR


def _pipe_dir(pipeline_id: str) -> Path:
    d = WORKSPACE_DIR / pipeline_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_branch(*, pipeline_id: str, name: str, base: str = "main") -> dict:
    p = _pipe_dir(pipeline_id) / "branch.json"
    p.write_text(json.dumps({"name": name, "base": base}, indent=2))
    return {"branch": name, "base": base, "created_at": time.time()}


def write_file(*, pipeline_id: str, path: str, content: str) -> dict:
    """Stage a file write inside the pipeline's workspace."""
    target = _pipe_dir(pipeline_id) / "files" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"path": path, "bytes": len(content)}


def commit(*, pipeline_id: str, message: str, files: list[str] | None = None) -> dict:
    p = _pipe_dir(pipeline_id) / "commits.jsonl"
    rec = {"ts": time.time(), "message": message, "files": files or []}
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"sha": f"sim-{int(time.time())}", "message": message}


def push_branch(*, pipeline_id: str, branch: str, remote: str = "origin") -> dict:
    p = _pipe_dir(pipeline_id) / "push.json"
    p.write_text(json.dumps({"branch": branch, "remote": remote}, indent=2))
    return {"pushed": True, "branch": branch, "remote": remote}


def open_pr(*, pipeline_id: str, title: str, body: str, branch: str, base: str = "main") -> dict:
    p = _pipe_dir(pipeline_id) / "pr.json"
    rec = {
        "url": f"https://github.example/owner/repo/pull/sim-{int(time.time())}",
        "title": title,
        "body": body,
        "branch": branch,
        "base": base,
    }
    p.write_text(json.dumps(rec, indent=2))
    return rec


_GH_COMMENT_MARKER = "<!-- ai-cicd-review -->"


def _post_or_update_github_comment(repo: str, pr_number: int, body: str) -> dict:
    """Find existing AI-CICD comment on the PR (by hidden marker) and update it,
    or create a new one. Idempotent — multiple pipeline runs won't stack comments.

    Activates only when GITHUB_TOKEN env is set. Errors don't fail the pipeline:
    posting is best-effort, the audit log + data/runs are the source of truth.
    """
    import os
    import httpx

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return {"skipped": "GITHUB_TOKEN not set"}

    body_with_marker = body if _GH_COMMENT_MARKER in body else f"{_GH_COMMENT_MARKER}\n{body}"
    headers = {
        "Accept":               "application/vnd.github+json",
        "Authorization":        f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{repo}"

    with httpx.Client(headers=headers, timeout=15) as cli:
        r = cli.get(f"{base}/issues/{pr_number}/comments", params={"per_page": 100})
        r.raise_for_status()
        existing = next(
            (c for c in r.json() if _GH_COMMENT_MARKER in (c.get("body") or "")),
            None,
        )
        if existing:
            r = cli.patch(f"{base}/issues/comments/{existing['id']}",
                          json={"body": body_with_marker})
            r.raise_for_status()
            return {"comment_url": r.json().get("html_url"), "updated": True,
                    "comment_id": existing["id"]}
        r = cli.post(f"{base}/issues/{pr_number}/comments",
                     json={"body": body_with_marker})
        r.raise_for_status()
        return {"comment_url": r.json().get("html_url"), "updated": False,
                "comment_id": r.json().get("id")}


def comment_pr(*, pipeline_id: str, body: str, pr_number: int | None = None,
               repo: str | None = None) -> dict:
    """Record the comment locally AND, if GITHUB_TOKEN + repo + pr_number are
    all present, post (or update) the comment on the actual GitHub PR.

    Idempotent: hidden marker `<!-- ai-cicd-review -->` lets us update in place
    instead of stacking on every push.
    """
    # Always record locally — source of truth even if GitHub posting fails.
    p = _pipe_dir(pipeline_id) / "comments.jsonl"
    rec = {"ts": time.time(), "pr": pr_number, "repo": repo, "body": body}
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")

    gh_result: dict | None = None
    if repo and pr_number:
        try:
            gh_result = _post_or_update_github_comment(repo, pr_number, body)
        except Exception as exc:                  # noqa: BLE001 — best-effort
            gh_result = {"error": str(exc)[:200]}

    return {"posted": True, "preview": body[:200], "github": gh_result}


def merge_pr(*, pipeline_id: str, pr_number: int, strategy: str = "squash") -> dict:
    p = _pipe_dir(pipeline_id) / "merge.json"
    rec = {"pr": pr_number, "strategy": strategy, "merged_at": time.time()}
    p.write_text(json.dumps(rec, indent=2))
    return rec


# --------------------- Deployment (simulated) ---------------------

def deploy_staging(*, pipeline_id: str, version: str = "candidate") -> dict:
    return _record_deploy(pipeline_id, "staging", version)


def deploy_canary(*, pipeline_id: str, version: str = "candidate", percentage: int = 5) -> dict:
    rec = _record_deploy(pipeline_id, "canary", version)
    rec["percentage"] = percentage
    rec["metrics"] = {"error_rate": 0.001, "p99_ms": 120}
    return rec


def deploy_production(*, pipeline_id: str, version: str = "candidate") -> dict:
    return _record_deploy(pipeline_id, "production", version)


def rollback(*, pipeline_id: str, to_version: str = "previous") -> dict:
    return _record_deploy(pipeline_id, "rollback", to_version)


def _record_deploy(pipeline_id: str, target: str, version: str) -> dict:
    p = _pipe_dir(pipeline_id) / "deploys.jsonl"
    rec: dict[str, Any] = {
        "ts": time.time(),
        "target": target,
        "version": version,
        "status": "ok",
    }
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
