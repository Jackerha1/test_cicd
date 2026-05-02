"""Trigger Layer.

In a real deployment this is a FastAPI route receiving GitHub webhooks. For
the MVP we accept events from a JSON file (so the demo runs entirely local).

An "event" is a normalized object the rest of the pipeline consumes. Real
webhooks get adapted to this shape here so downstream code never needs to
know about provider-specific payloads.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.audit import log as audit


class Event(BaseModel):
    """Normalized event consumed by the orchestrator."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pipeline_id: str = Field(default_factory=lambda: f"pipe-{uuid.uuid4().hex[:8]}")
    kind: str                              # "issue" | "pull_request" | "comment"
    action: str                            # "opened" | "updated" | "commented"
    repo: str                              # "owner/name"
    number: Optional[int] = None
    title: str = ""
    body: str = ""
    author: str = ""
    branch: Optional[str] = None
    base_branch: Optional[str] = "main"
    files_changed: list[str] = Field(default_factory=list)
    diff: str = ""
    labels: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


def load_event(path: str | Path) -> Event:
    """Read a normalized event from a JSON file (used by the demo CLI)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Event file not found: {p}")
    data = json.loads(p.read_text())
    event = Event(**data)
    audit.log(
        pipeline_id=event.pipeline_id,
        actor="trigger",
        action="event_received",
        target=f"{event.kind}/{event.repo}#{event.number}",
        decision="info",
        payload={"author": event.author, "title": event.title},
    )
    return event
