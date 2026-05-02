"""Data flywheel writer.

Karpathy framing: every pipeline run produces a labeled training example
for free — input (event), output (agent decisions), label (final verdict +
human approval if any). Persist them in a flat JSONL under data/runs/ so
they can be replayed, scored, or used to fine-tune later.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.config import ROOT

DATASET_PATH = ROOT / "data" / "runs"


def write_run(*, pipeline_id: str, event: dict, result: dict) -> Path:
    DATASET_PATH.mkdir(parents=True, exist_ok=True)
    p = DATASET_PATH / f"{pipeline_id}.json"
    payload = {
        "pipeline_id": pipeline_id,
        "ts": time.time(),
        "event": event,
        "result": result,
    }
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p
