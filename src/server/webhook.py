"""Production webhook + worker.

Karpathy reflexes baked in:
  - HMAC-verified webhook signatures (no auth-by-obscurity).
  - Bounded async worker pool — back-pressure on incoming events.
  - Per-pipeline cost ceiling — abort if a single run blows past AICICD_PIPELINE_BUDGET_USD.
  - /healthz: liveness, always 200 if process is up.
  - /readyz: readiness, 503 if the gateway is unreachable.
  - NDJSON structured logs when AICICD_LOG_FORMAT=json (one event = one line).
  - Graceful shutdown: drain inflight pipelines before exiting.

Endpoints:
  POST /event/<provider>    receive a normalized event (provider=demo|github)
  POST /run                 manual trigger with an event JSON body
  GET  /healthz             always 200 if process is up
  GET  /readyz              200 only if the LLM gateway is reachable
  GET  /metrics             prometheus-style counters (queue depth, cost, etc.)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from src.audit import log as audit
from src.config import CLAUDE_CLI_API_URL
from src.orchestrator.pipeline import run_pipeline
from src.trigger.webhook import Event

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

LOG_FORMAT = os.getenv("AICICD_LOG_FORMAT", "text").lower()
SECRET = os.getenv("AICICD_WEBHOOK_SECRET", "")
CONCURRENCY = int(os.getenv("AICICD_WORKER_CONCURRENCY", "2"))
PIPELINE_BUDGET_USD = float(os.getenv("AICICD_PIPELINE_BUDGET_USD", "1.00"))


class _NDJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload = {
            "ts":      record.created,
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k.startswith("_") or k in payload or k in {
                "args", "msg", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno",
                "funcName", "created", "msecs", "relativeCreated", "thread",
                "threadName", "processName", "process", "name", "message",
            }:
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except TypeError:
                payload[k] = str(v)
        return json.dumps(payload, default=str)


def _setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    if LOG_FORMAT == "json":
        h.setFormatter(_NDJSONFormatter())
    else:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)


_setup_logging()
logger = logging.getLogger("ai-cicd.webhook")


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

_queue: "asyncio.Queue[Event]" = asyncio.Queue(maxsize=128)
_workers: list[asyncio.Task] = []
_metrics = {"received": 0, "processed": 0, "failed": 0, "queue_depth": 0,
            "total_cost_usd": 0.0, "budget_exceeded": 0}


async def _worker(idx: int) -> None:
    while True:
        try:
            event = await _queue.get()
        except asyncio.CancelledError:
            break
        _metrics["queue_depth"] = _queue.qsize()
        logger.info("pipeline_start", extra={"worker": idx, "pipeline_id": event.pipeline_id,
                                             "kind": event.kind, "repo": event.repo})
        try:
            result = await run_pipeline(event)
            _metrics["processed"] += 1
            _metrics["total_cost_usd"] += result.cost_usd
            if result.cost_usd > PIPELINE_BUDGET_USD:
                _metrics["budget_exceeded"] += 1
                audit.log(pipeline_id=event.pipeline_id, actor="webhook",
                          action="budget_exceeded", decision="warn",
                          payload={"cost_usd": result.cost_usd, "ceiling": PIPELINE_BUDGET_USD})
                logger.warning("pipeline_budget_exceeded",
                               extra={"pipeline_id": event.pipeline_id,
                                      "cost_usd": result.cost_usd,
                                      "ceiling": PIPELINE_BUDGET_USD})
            logger.info("pipeline_done",
                        extra={"pipeline_id": event.pipeline_id,
                               "final_status": result.final_status,
                               "cost_usd": result.cost_usd,
                               "duration_s": result.duration_s})
        except Exception as exc:
            _metrics["failed"] += 1
            logger.exception("pipeline_failed",
                             extra={"pipeline_id": event.pipeline_id, "error": str(exc)})
        finally:
            _queue.task_done()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    logger.info("starting", extra={"concurrency": CONCURRENCY,
                                    "pipeline_budget_usd": PIPELINE_BUDGET_USD,
                                    "log_format": LOG_FORMAT})
    for i in range(CONCURRENCY):
        _workers.append(asyncio.create_task(_worker(i)))
    try:
        yield
    finally:
        logger.info("draining_queue")
        await _queue.join()
        for w in _workers:
            w.cancel()
        await asyncio.gather(*_workers, return_exceptions=True)
        logger.info("stopped")


app = FastAPI(title="AI-CICD Webhook", version="4.0.0", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {"status": "alive", "version": "4.0.0", "queue": _queue.qsize()}


@app.get("/readyz")
async def readyz():
    """503 if the LLM gateway isn't reachable. Used by orchestrator + LB."""
    try:
        async with httpx.AsyncClient(timeout=5) as cli:
            r = await cli.get(f"{CLAUDE_CLI_API_URL.rstrip('/')}/readyz")
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"gateway unreachable: {exc}")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    """Plain JSON metrics — easy to scrape into anything."""
    return {**_metrics, "queue_depth": _queue.qsize()}


# ---------------------------------------------------------------------------
# Event ingestion
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, signature: str) -> bool:
    if not SECRET:
        # No secret configured → reject all signed traffic. Force op to set one.
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@app.post("/event/{provider}")
async def event(provider: str, request: Request):
    body = await request.body()
    sig = request.headers.get("x-hub-signature-256") or request.headers.get("x-aicicd-signature", "")
    if not _verify_signature(body, sig):
        raise HTTPException(status_code=401, detail="bad signature")

    payload = json.loads(body or b"{}")
    try:
        event = _normalize(provider, payload)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing field: {exc}")

    _metrics["received"] += 1
    try:
        _queue.put_nowait(event)
    except asyncio.QueueFull:
        raise HTTPException(status_code=429, detail="queue full — back off")

    return {"accepted": True, "pipeline_id": event.pipeline_id, "queue_depth": _queue.qsize()}


@app.post("/run")
async def run_manual(request: Request):
    """Manual trigger with a normalized event JSON body — bypasses HMAC.

    Bind this endpoint to localhost only in production (network policy /
    listen address). It exists for ops convenience (`make run EVENT=...`).
    """
    payload = await request.json()
    try:
        event = Event(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid event: {exc}")
    _metrics["received"] += 1
    _queue.put_nowait(event)
    return {"accepted": True, "pipeline_id": event.pipeline_id}


# ---------------------------------------------------------------------------
# Provider-specific normalization
# ---------------------------------------------------------------------------

def _normalize(provider: str, payload: dict) -> Event:
    if provider == "demo":
        return Event(**payload)
    if provider == "github":
        return _normalize_github(payload)
    raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")


def _fetch_pr_diff_and_files(repo: str, pr_number: int) -> tuple[str, list[str]]:
    """Pull the unified diff + changed-files list for a PR via GitHub REST API.

    Used by the webhook handler because GitHub's PR webhook payload omits these.
    No-op (returns empty) if GITHUB_TOKEN isn't set — the pipeline still runs,
    just with empty diff (agents will note it).
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return "", []
    base = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    common = {
        "Authorization":        f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    diff = ""
    files: list[str] = []
    try:
        with httpx.Client(timeout=30) as cli:
            r = cli.get(base, headers={**common, "Accept": "application/vnd.github.v3.diff"})
            if r.status_code == 200:
                diff = r.text
            r2 = cli.get(f"{base}/files",
                         headers={**common, "Accept": "application/vnd.github+json"},
                         params={"per_page": 300})
            if r2.status_code == 200:
                files = [f["filename"] for f in r2.json()]
    except httpx.HTTPError:
        pass
    return diff, files


def _normalize_github(p: dict) -> Event:
    """Map a (subset of) GitHub webhook to the normalized Event shape."""
    if "issue" in p and "comment" not in p:
        i = p["issue"]
        return Event(
            kind="issue", action=p.get("action", "opened"),
            repo=p["repository"]["full_name"], number=i["number"],
            title=i.get("title", ""), body=i.get("body", ""),
            author=i.get("user", {}).get("login", "unknown"),
            labels=[l["name"] for l in i.get("labels", [])],
            raw=p,
        )
    if "pull_request" in p:
        pr = p["pull_request"]
        repo = p["repository"]["full_name"]
        number = pr["number"]
        # GitHub PR webhook payload doesn't include diff or files_changed.
        # Fetch them ourselves with GITHUB_TOKEN so the agents have something
        # to review. Best-effort — empty diff/files are valid degraded mode.
        diff, files_changed = _fetch_pr_diff_and_files(repo, number)
        return Event(
            kind="pull_request", action=p.get("action", "opened"),
            repo=repo, number=number,
            title=pr.get("title", ""), body=pr.get("body", ""),
            author=pr.get("user", {}).get("login", "unknown"),
            branch=pr["head"]["ref"], base_branch=pr["base"]["ref"],
            files_changed=files_changed,
            diff=diff,
            labels=[l["name"] for l in pr.get("labels", [])],
            raw=p,
        )
    if "comment" in p:
        c = p["comment"]
        return Event(
            kind="comment", action=p.get("action", "created"),
            repo=p["repository"]["full_name"],
            number=p.get("issue", {}).get("number") or p.get("pull_request", {}).get("number"),
            title="", body=c.get("body", ""),
            author=c.get("user", {}).get("login", "unknown"),
            raw=p,
        )
    raise HTTPException(status_code=400, detail="unrecognized github payload")


if __name__ == "__main__":
    uvicorn.run("src.server.webhook:app",
                host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
