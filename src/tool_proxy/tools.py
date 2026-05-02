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


def comment_pr(*, pipeline_id: str, body: str, pr_number: int | None = None) -> dict:
    p = _pipe_dir(pipeline_id) / "comments.jsonl"
    rec = {"ts": time.time(), "pr": pr_number, "body": body}
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"posted": True, "preview": body[:200]}


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
