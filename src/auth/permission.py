"""Auth & Permission Check.

Decides whether an incoming event is from a trusted source. An untrusted
source isn't necessarily *blocked* — but downstream agents see
`event.untrusted = True` which forces stricter policy choices (e.g. no
auto-merge regardless of risk_level).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.audit import log as audit
from src.config import POLICIES_DIR
from src.trigger.webhook import Event


def _load() -> dict:
    p = POLICIES_DIR / "allowed_authors.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


class AuthResult:
    def __init__(self, *, allowed: bool, trusted: bool, reason: str):
        self.allowed = allowed
        self.trusted = trusted
        self.reason = reason

    def __repr__(self):
        return f"AuthResult(allowed={self.allowed}, trusted={self.trusted}, reason={self.reason!r})"


def check_event(event: Event) -> AuthResult:
    cfg = _load()
    trusted_authors = set(cfg.get("trusted_authors", []))
    trusted_bots = set(cfg.get("trusted_bots", []))

    # All events are *allowed* into the pipeline (we still want to triage them);
    # the question is whether the actor is *trusted* enough to skip extra gates.
    is_trusted = event.author in trusted_authors or event.author in trusted_bots

    audit.log(
        pipeline_id=event.pipeline_id,
        actor="auth",
        action="auth_check",
        target=event.author,
        decision="allowed" if is_trusted else "info",
        payload={"trusted": is_trusted},
    )

    return AuthResult(
        allowed=True,
        trusted=is_trusted,
        reason="trusted author" if is_trusted else "untrusted author — extra gates apply",
    )
