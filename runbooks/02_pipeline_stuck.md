# 02 — Pipeline stuck / queue backed up

## Symptom

- `curl /metrics` shows `queue_depth` growing and not draining.
- Webhooks return `429 queue full`.
- `make logs-pipeline` shows `pipeline_start` events without matching
  `pipeline_done`.

## First check

```bash
curl -s http://localhost:8000/metrics
make logs-pipeline | tail -50
```

Compute time-in-queue: `processed` over `received` should track close to 1.0
in steady state. If much lower, work is queueing faster than it processes.

## Mitigate

**Increase concurrency** (cheapest fix):
```bash
docker compose down
AICICD_WORKER_CONCURRENCY=8 docker compose up -d
make ready
```

**One stuck pipeline blocking the queue** (worker thread hung on a long LLM call):
```bash
# Find the offending pipeline
make logs-pipeline | grep -i 'agent_start' | tail -5
# That gives you `pipeline_id`. Inspect:
make audit PIPELINE_ID=pipe-...
# If clearly stuck on an LLM call: kill the pipeline container, queue drains.
docker compose restart pipeline
```

The queue is in-memory, so unprocessed events are lost on restart — accept
that for now (Karpathy: don't add Redis until you actually need it). Fix-forward.

## Root-cause

1. **CLI hang on a malformed prompt**: check `gateway` logs for `timed out`.
   Increase `CLAUDE_CALL_TIMEOUT` if legitimate, OR shrink the prompt.
2. **Validation post-rule looping**: agent retries 3 times each, hits the
   same `post_validate` failure each time. Look at `audit` table for
   `agent_failed` rows and read the `error` field.
3. **Receiving more events than agents can process**: scale up
   `AICICD_WORKER_CONCURRENCY`, OR rate-limit upstream.

## Prevention

- Per-pipeline timeout (TODO add): `AICICD_PIPELINE_TIMEOUT_S=900`. Right now
  there's no overall ceiling, just per-call.
- Alert on `queue_depth > 32` for 5 min.
- Eval suite catches the loop-on-post-validate case before it hits prod —
  add a regression case.
