---
name: ai-cicd-triage
description: Run only the Triage agent on an event. Use when the user wants to classify an issue/PR (kind, severity, scope, suggested agents) without running the full pipeline. Examples - "triage this issue", "what kind of change is this PR".
---

# Run Triage agent in isolation

Calls the Triage agent on an event to classify it.

## Steps

1. Read the event file the user references (under `examples/` or a path they give).
2. Run:
   ```bash
   python -c "
   import asyncio, json
   from src.trigger.webhook import load_event
   from src.context.builder import build
   from src.agents import TriageAgent
   ev = load_event('PATH_HERE')
   ctx = build(ev, trusted=True)
   r = asyncio.run(TriageAgent().run(ctx))
   print(json.dumps(r.to_dict(), indent=2, default=str))
   "
   ```

The output JSON conforms to `schemas/triage.json`.
