# 03 — Lethal trifecta detected

## Symptom

- `make trifecta-audit` fails (exit 2) with one or more `LETHAL` rows.
- CI gate refuses to deploy.

This means an agent in `policies/approval_matrix.yaml` now holds all three:
**untrusted input** + **private data** + **exfiltration**.

## First check

```bash
make trifecta-audit
```

Read the lethal row(s). They list which legs the agent has.

## Mitigate IMMEDIATELY

**Do not deploy.** The pipeline cannot proceed safely. Two options:

**Option A — strip the exfiltration leg**:
```yaml
# policies/approval_matrix.yaml
agent_capabilities:
  bug_fix: [create_branch, write_file, commit]   # remove push_branch / open_pr
```

**Option B — strip the private-data leg**:
- Remove the agent's read-access to secrets / customer data / prod DB.
- Today the system has zero `_PRIVATE_DATA_AGENTS` by design. If it
  changed, audit the diff in `src/audit/trifecta.py`.

Re-run `make trifecta-audit` until clean.

## Root-cause

Inspect the most recent change to either:
- `policies/approval_matrix.yaml` — capability matrix
- `src/audit/trifecta.py` — `_PRIVATE_DATA_AGENTS`, `_UNTRUSTED_INPUT_AGENTS`,
  `_EXFIL_ACTIONS` sets
- `src/agents/<name>.py` — agent now reads/writes new surface

```bash
git log -p -5 policies/approval_matrix.yaml src/audit/trifecta.py
```

## Prevention

- `make trifecta-audit` is wired into CI as a hard gate. Don't bypass.
- Quarterly review: are the `_PRIVATE_DATA_AGENTS` and `_UNTRUSTED_INPUT_AGENTS`
  sets still accurate after recent feature work?
- Karpathy: an agent should never hold all three legs. That's an architecture
  invariant, not a runtime check we can lean on.
