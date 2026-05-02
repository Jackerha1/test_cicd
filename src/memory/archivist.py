"""Archivist — runs after a pipeline ends to update repo memory.

Karpathy framing: this closes the data flywheel. Outcomes from one run
feed the context of the next. Cheap, deterministic — no LLM call.
"""
from __future__ import annotations

from src.audit import log as audit
from src.memory import store


def archive(*, pipeline_id: str, repo: str, event_title: str,
            final_status: str, files_changed: list[str], summary: str,
            reflector_root_cause: str | None = None) -> None:
    if not repo:
        return

    store.append_patch(
        repo,
        issue_title=event_title,
        files_changed=files_changed,
        summary=summary or "(no summary)",
        verdict=final_status,
    )

    if reflector_root_cause and reflector_root_cause not in (
        "policy_block", "infrastructure_error",
    ):
        store.append_pitfall(
            repo,
            f"[{event_title!r}] root cause: {reflector_root_cause}",
        )

    audit.log(
        pipeline_id=pipeline_id, actor="archivist",
        action="memory_updated", target=repo, decision="info",
        payload={"final_status": final_status,
                 "reflector_root_cause": reflector_root_cause},
    )
