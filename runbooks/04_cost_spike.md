# 04 — Cost spike / budget exceeded

## Symptom

- Log lines `pipeline_budget_exceeded` in `make logs-pipeline`.
- `make cost PIPELINE_ID=...` shows a single agent dominating the run cost.
- `/metrics` `total_cost_usd` rising faster than `processed`.

## First check

```bash
# Top cost pipelines from the audit DB
docker compose exec pipeline sqlite3 /app/logs/audit.db \
  "SELECT pipeline_id, json_extract(payload_json, '$.telemetry.cost_usd') as cost \
   FROM audit WHERE action='agent_done' \
   ORDER BY cost DESC LIMIT 10"
```

Pick the worst pipeline_id, drill in:
```bash
make cost PIPELINE_ID=pipe-...
```

You're looking for one agent with abnormal `tokens_in` (often) — usually
context bloat from `prior_outputs` or oversized memory injection.

## Mitigate

**Per-pipeline budget**: already enforced via `AICICD_PIPELINE_BUDGET_USD`
(default $1.00). Lowering it just makes runs fail loud:
```bash
AICICD_PIPELINE_BUDGET_USD=0.50 docker compose up -d
```

**Per-agent cap** (TODO): not implemented yet — currently the budget is
checked AFTER the run, not during. For now, kill long-running pipelines
manually if cost is the concern: `docker compose restart pipeline`.

**Cap context size**: `Context Builder` truncates diff at 12000 chars
(`for_agent(self.name, max_diff_chars=...)` in `src/context/builder.py`).
If a single change blew past, lower it temporarily.

## Root-cause

1. **Memory layer grew unbounded**: per-repo `memory/<repo>/past_patches.jsonl`
   keeps last 10 patches in context — but if entries got huge, that's >10K tokens.
   Trim:
   ```bash
   tail -10 memory/<repo>/past_patches.jsonl > /tmp/x && mv /tmp/x memory/<repo>/past_patches.jsonl
   ```

2. **Critic running too aggressively**: Critic sees the producer's full output.
   If the producer emitted a huge patch, Critic gets a huge context. Consider
   running Critic only on the Validation output (already current behavior).

3. **Wrong model routed for a cheap task**: `make providers` and check.
   Triage / Documentation should be on `gemini` (or `gpt-5-nano`); Validation
   stays on top model.

4. **Same pattern keeps hitting AI when it could be a rule**: this is the
   highest-leverage cost fix. Follow [runbook 05 — pattern promotion](05_pattern_promotion.md)
   to ratchet the AI signal into a deterministic gate. Same security
   guarantee, $0 cost, sub-50ms latency.

## Prevention

- Add CI gate: `make eval` reports cost per case; fail if it doubles vs the
  previous baseline (Karpathy: regress on cost is a regress).
- Quarterly: re-run `make compare` to verify cheaper providers haven't gotten
  good enough to handle agents currently routed to the expensive ones.
- Alert on `total_cost_usd` daily delta exceeding budget threshold.
