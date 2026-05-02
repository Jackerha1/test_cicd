"""Per-repo learned memory.

Karpathy's framing: AI agents without memory are amnesic — they re-learn the
same conventions every run. We persist a small set of distilled facts per
repo and inject them into every Context Builder.

What lives here:
  conventions.md   — code style / naming patterns observed across past PRs
  past_patches.jsonl — historical (issue → patch) pairs
  pitfalls.md      — recurring mistakes the Reflector flagged

Updates are append-only and human-readable. The Archivist hook
(`src/memory/archivist.py`) writes to it after each successful pipeline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.config import ROOT

MEMORY_ROOT = ROOT / "memory"


def _slug(repo: str) -> str:
    return repo.replace("/", "__")


def repo_dir(repo: str) -> Path:
    d = MEMORY_ROOT / _slug(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(repo: str) -> dict:
    """Load all memory for a repo as a dict the Context Builder can inject."""
    d = repo_dir(repo)
    out = {"repo": repo}
    conventions = d / "conventions.md"
    pitfalls = d / "pitfalls.md"
    past = d / "past_patches.jsonl"
    if conventions.exists():
        out["conventions"] = conventions.read_text()[:2000]
    if pitfalls.exists():
        out["pitfalls"] = pitfalls.read_text()[:2000]
    if past.exists():
        rows = [json.loads(l) for l in past.read_text().splitlines() if l.strip()]
        # Keep only the 10 most recent — context is precious.
        out["past_patches"] = rows[-10:]
    return out


def append_patch(repo: str, *, issue_title: str, files_changed: list[str],
                 summary: str, verdict: str) -> None:
    p = repo_dir(repo) / "past_patches.jsonl"
    rec = {
        "ts": time.time(),
        "issue_title": issue_title,
        "files_changed": files_changed,
        "summary": summary,
        "verdict": verdict,
    }
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def append_pitfall(repo: str, line: str) -> None:
    p = repo_dir(repo) / "pitfalls.md"
    with p.open("a") as f:
        f.write(f"- {line}\n")


def append_convention(repo: str, line: str) -> None:
    p = repo_dir(repo) / "conventions.md"
    with p.open("a") as f:
        f.write(f"- {line}\n")
