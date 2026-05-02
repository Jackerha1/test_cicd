"""LLM-OS Kernel — DAG scheduler for agents.

Karpathy's "LLM as OS" analogy: the kernel scheduler runs processes
(agents) according to a dependency graph; independent processes run
concurrently. The orchestrator declares the DAG; the kernel executes it.

Why this exists: the original orchestrator ran every agent sequentially,
which is wasteful when (e.g.) Security Scan and Code Review both depend
on Bug Fix but not on each other — they should run in parallel.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from src.audit import log as audit


@dataclass
class Task:
    name: str
    fn:   Callable[[], Awaitable[Any]]   # nullary coroutine factory
    deps: list[str] = field(default_factory=list)


async def run_dag(tasks: list[Task], *, pipeline_id: str = "n/a") -> dict[str, Any]:
    """Execute a DAG of agent tasks. Independent nodes run concurrently.

    Returns {task_name: result_or_exception}. Tasks whose deps fail are
    skipped and recorded as `KernelSkipped(reason)`.
    """
    by_name = {t.name: t for t in tasks}
    pending = set(by_name)
    done: dict[str, Any] = {}
    failed: set[str] = set()

    audit.log(pipeline_id=pipeline_id, actor="kernel", action="dag_start",
              decision="info", payload={"tasks": list(by_name)})

    while pending:
        # All tasks whose deps are satisfied (and no upstream failure).
        ready = [
            n for n in pending
            if all(d in done and d not in failed for d in by_name[n].deps)
        ]
        if not ready:
            # Either every remaining task is blocked on a failed upstream,
            # or there's a cycle. Either way, skip them.
            for n in pending:
                done[n] = KernelSkipped(reason=f"upstream failed or unreachable: deps={by_name[n].deps}")
                failed.add(n)
            break

        results = await asyncio.gather(
            *[_safe_call(by_name[n].fn) for n in ready],
            return_exceptions=False,
        )
        for n, r in zip(ready, results):
            done[n] = r
            if isinstance(r, BaseException) or _is_failed_agent_result(r):
                failed.add(n)
        pending -= set(ready)

    audit.log(pipeline_id=pipeline_id, actor="kernel", action="dag_done",
              decision="info",
              payload={"failed": sorted(failed), "ok": sorted(set(done) - failed)})
    return done


async def _safe_call(fn):
    try:
        return await fn()
    except BaseException as exc:  # noqa: BLE001 — we want to capture everything
        return exc


def _is_failed_agent_result(r: Any) -> bool:
    return getattr(r, "ok", True) is False


@dataclass
class KernelSkipped:
    reason: str
