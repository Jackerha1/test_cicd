---
name: ai-cicd-audit
description: Inspect the immutable audit trail for a previous AI-CICD pipeline run. Shows every agent invocation, policy decision, tool call, and human approval in time order. Use when the user asks "what did the pipeline do" or "why was that blocked".
---

# Audit a pipeline run

The pipeline writes every step to `logs/audit.db` (SQLite, append-only).

## Steps

1. Find the pipeline_id (printed by `ai-cicd run` and stored in `logs/<pipeline_id>.json`).

2. Dump the trail:
   ```bash
   python -m src.cli audit <pipeline_id>
   ```

3. For deeper inspection (raw payloads):
   ```bash
   sqlite3 logs/audit.db "SELECT * FROM audit WHERE pipeline_id='<pipeline_id>' ORDER BY ts;"
   ```

## What you'll see

- `trigger.event_received` — first row, who/what triggered
- `auth.auth_check` — trusted vs untrusted author
- `policy_engine.classify` — risk level + which rule fired
- `<agent>.agent_start` / `agent_done` / `agent_failed` — every agent call
- `tool_proxy.authorize:<action>` — what was asked
- `tool_proxy.execute:<action>` — what actually ran
- `approval_gate.approval_requested` / `approval_decision` — human gates
- `orchestrator.pipeline_done` — final status
