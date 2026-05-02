"""Immutable audit log backed by SQLite.

Every step of the pipeline writes here: trigger receipt, agent invocations,
policy decisions, approvals, tool calls, deploys. Rows are append-only —
deletion/update is intentionally not exposed.

Design choice: SQLite is fine for the MVP. For production swap with Postgres
or push to an external SIEM. The schema is small on purpose.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

from src.config import AUDIT_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id              TEXT PRIMARY KEY,
    ts              REAL NOT NULL,
    pipeline_id     TEXT NOT NULL,
    actor           TEXT NOT NULL,        -- "trigger" | "orchestrator" | agent name | "policy" | "human"
    action          TEXT NOT NULL,
    target          TEXT,
    risk_level      TEXT,
    decision        TEXT,                 -- "allowed" | "denied" | "approved" | "blocked" | "info"
    payload_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_pipeline ON audit(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts       ON audit(ts);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(AUDIT_DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


def log(
    *,
    pipeline_id: str,
    actor: str,
    action: str,
    target: Optional[str] = None,
    risk_level: Optional[str] = None,
    decision: Optional[str] = None,
    payload: Optional[Any] = None,
) -> str:
    """Append one audit row. Returns the row id."""
    init_db()
    row_id = str(uuid.uuid4())
    payload_json = json.dumps(payload, default=str) if payload is not None else None
    with _conn() as con:
        con.execute(
            "INSERT INTO audit (id, ts, pipeline_id, actor, action, target, risk_level, decision, payload_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                time.time(),
                pipeline_id,
                actor,
                action,
                target,
                risk_level,
                decision,
                payload_json,
            ),
        )
    return row_id


def fetch_pipeline(pipeline_id: str) -> list[dict]:
    """Return all audit rows for a given pipeline, ordered by time."""
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, ts, pipeline_id, actor, action, target, risk_level, decision, payload_json"
            " FROM audit WHERE pipeline_id = ? ORDER BY ts ASC",
            (pipeline_id,),
        ).fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "ts": r[1],
            "pipeline_id": r[2],
            "actor": r[3],
            "action": r[4],
            "target": r[5],
            "risk_level": r[6],
            "decision": r[7],
            "payload": json.loads(r[8]) if r[8] else None,
        })
    return out
