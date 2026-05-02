---
name: ai-cicd-run
description: Run the full AI-CICD pipeline (9 agents, policy engine, validation, approval gate) against an event JSON file in this repo. Use when the user wants to execute the demo end-to-end or process an issue/PR through the agents. Examples - "run the cicd on the login bug example", "trigger the auto-fix flow", "review pr_auth_change.json".
---

# Run AI-CICD pipeline

This skill runs the project's pipeline against a normalized event file in `examples/`.

## When to use

The user wants to execute the multi-agent pipeline end-to-end against one of:
- an `examples/*.json` event
- a custom event file they hand you

## Steps

1. Make sure `claude-cli-api` is running:
   ```bash
   cd claude-cli-api && PLANNER_BACKEND=claude uvicorn main:app --port 8765 &
   ```
   Probe with `python -m src.cli health`.

2. Pick an event file from `examples/` (or one the user provides). List options with:
   ```bash
   python -m src.cli list
   ```

3. Run the pipeline:
   ```bash
   python -m src.cli run examples/issue_login_bug.json
   ```

4. Inspect the audit trail:
   ```bash
   python -m src.cli audit <pipeline_id>
   ```

## What this exercises

- Trigger Layer → Auth → Context Builder → Policy Engine
- All 9 agents in their flow order (PR review or Auto Fix depending on event kind)
- Tool Proxy gating (high-risk actions require approval)
- Validation Agent's hard cross-checks
- Audit log persistence (SQLite at `logs/audit.db`)

## Important

- This skill RUNS pipeline code; it does not modify the agent definitions.
  To change agent behavior, edit `prompts/<agent>.md` or `src/agents/<agent>.py`.
- The `pr_secrets_attempt.json` example MUST be blocked by policy — that's the
  expected demonstration of the deterministic block rule.
