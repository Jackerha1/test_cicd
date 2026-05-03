# Runbooks

> Karpathy: "Ops > heroics. If you wake up at 3am, you should not have to think."

There are two kinds of runbook here. **Failure-mode runbooks** (01–04) tell
you what to do when something breaks at 3am. **SOPs** (05+) describe
recurring operational workflows you'll do during the day.

## Failure-mode runbooks

Each follows the same shape:
1. **Symptom** — what the alert / log line says
2. **First check** — the one command that confirms the diagnosis
3. **Mitigate** — restore service
4. **Root-cause** — find the actual problem
5. **Prevention** — what to add so this doesn't happen again

| # | Runbook | When |
|---|---|---|
| 01 | [Provider down (claude / gemini CLI)](01_provider_down.md) | `make ready` shows gateway unhealthy or `pipeline_failed` rate spikes |
| 02 | [Pipeline stuck / queue backed up](02_pipeline_stuck.md) | `/metrics` `queue_depth` grows without bound |
| 03 | [Lethal trifecta detected](03_lethal_trifecta.md) | `make trifecta-audit` fails; CI blocks deploy |
| 04 | [Cost spike / budget exceeded](04_cost_spike.md) | `pipeline_budget_exceeded` log lines, OR `make cost PIPELINE_ID=...` shows outliers |

## Standard operating procedures (SOPs)

| # | Runbook | When |
|---|---|---|
| 05 | [Pattern promotion (AI → deterministic rule)](05_pattern_promotion.md) | Reflector's `suggested_fix.kind` is `policy_edit`, OR same root cause appears 3+ times, OR a single agent dominates spend on a clearly-pattern-able issue |
