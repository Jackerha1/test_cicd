# 05 — Pattern promotion (AI → deterministic rule)

> **This is an SOP, not a failure-mode runbook.** Runbooks 01–04 tell you
> what to do when something breaks. This one tells you what to do when
> the AI keeps catching the same kind of thing.

## Trigger — when to follow this runbook

Any of these signals means a pattern is ready to promote:

1. **Reflector says so.** Run a `make audit` on a recently blocked pipeline
   and the Reflector's `suggested_fix.kind` is `policy_edit` (or `schema_edit`).
   That's the AI directly asking for a deterministic gate.

2. **Same root cause appears 3+ times.** Look at recent failed runs:
   ```bash
   sqlite3 logs/audit.db "
     SELECT json_extract(payload_json, '\$.root_cause') AS rc, COUNT(*)
     FROM audit
     WHERE action='root_cause' AND ts > strftime('%s','now','-30 days')
     GROUP BY rc ORDER BY 2 DESC"
   ```
   If a root cause repeats, AI is doing manual labour every time. Promote it.

3. **`make memory REPO=...` shows the same pitfall recurring.** The Archivist
   appended the same line twice — that's the data flywheel asking for help.

4. **Cost forensics show a single agent dominating spend** for a clearly-pattern-able
   class of issues. (You will pay this cost again on every PR until you promote.)

## Why we do it

Karpathy framing:

> **AI discovers patterns. Humans ratchet patterns into deterministic gates.
> AI moves on to discover the next pattern.**

The AI catching CWE-347 the second time is wasted compute. The AI catching it
the *first* time is what we're paying for.

Concrete number from pipeline `pipe-d58abf94` → `pipe-05242cca`:

| Same attack pattern | Before promotion | After promotion |
|---|---|---|
| Cost | $0.0612 | $0.0000 |
| Latency | 84.4s | 0.044s |
| Verdict | blocked | blocked (identical) |

Same security guarantee, **1900× faster, 100% cheaper**.

## Procedure (the canonical 6 steps)

### Step 1 — Confirm the pattern is real (not a one-off)

```bash
# Read the Reflector output for the pipeline that surfaced it
make audit PIPELINE_ID=pipe-...
ai-cicd reflect pipe-...
```

If the `root_cause` is something deterministic-shaped (`failed_security_scan`,
`scope_violation`, `policy_block`, `agent_format_error`) — promote candidate.

If the root cause is `agent_hallucination` or `validation_disagreement` —
**do NOT promote**. Those are AI-quality issues, not patterns.

### Step 2 — Find the smallest signature

What's the minimal regex / glob that catches the pattern but no false positives?

For the JWT-none case, the signature was three regexes:
```yaml
diff_contains:
  - "algorithms\\s*=\\s*\\[[^\\]]*['\"]none['\"]"   # Python: algorithms=['RS256','none']
  - "['\"]alg['\"]\\s*:\\s*['\"]none['\"]"          # JSON: "alg": "none"
  - "\\balg\\s*=\\s*['\"]none['\"]"                  # generic: alg='none'
```

**Test before promoting:** grep this regex over your repo HEAD. If it matches
anything legitimate, the regex is too greedy. Tighten it.

### Step 3 — Add the rule

Edit `policies/risk_rules.yaml`. Two match dimensions:

```yaml
rules:
  - id: <descriptive_snake_case_id>            # used in audit + reflector text
    match:
      paths:                                   # narrow to relevant surface
        - "src/auth/**"
        - "**/jwt*"
      diff_contains:                           # regex against unified diff
        - "<your tightened regex>"
    risk_level: critical                       # or low/medium/high
    require_human_approval: true               # almost always for promoted rules
    block: true                                # hard stop — no agent runs
    reason: "Short why. Promoted from <pipeline_id>."
```

Conventions:
- **Always include `Promoted from <pipeline_id>`** in `reason` — links rule
  back to the original AI signal for future archaeology.
- Use `block: true` only when the pattern is **always wrong**. If it's
  "should be human-reviewed but might be legitimate", use `require_human_approval`
  without `block`.
- Place the new rule **above** broader rules so it fires first.

### Step 4 — Add the regression test (NON-NEGOTIABLE)

Every promoted rule earns a test. No test → no promotion.

```yaml
# evals/cases/policy__<rule_id>.yaml
name: policy__<rule_id>
target: policy_engine
event: examples/<the example that originally surfaced it>.json
expect:
  rule_id:                <rule_id>
  risk_level:             critical
  block:                  true
  require_human_approval: true
```

Plus **at least one negative case** to catch over-firing:

```yaml
# evals/cases/policy__<some_other_event>_low.yaml
name: policy__<some_other_event>_low
target: policy_engine
event: examples/<unrelated benign event>.json
expect:
  rule_id: <expected_default_or_other_rule>     # NOT your new rule
  block:   false
```

This is the part that stops a future "let me clean up these old rules" PR
from silently disabling your gate.

### Step 5 — Verify locally

```bash
ai-cicd eval --target policy_engine
# Must show 100% pass. The new case + all prior cases.
```

If your new rule broke an old case → either your regex is too greedy
(fix the regex) or the old case was wrong (update it after thinking hard).

### Step 6 — Commit + push

```bash
git add policies/risk_rules.yaml evals/cases/policy__*.yaml
git commit -m "policy: promote <rule_id> from AI signal to deterministic block

Context: pipeline <pipeline_id> caught <CWE / pattern> in PR review using
full agent reasoning (\$X.XX, Ys). Reflector suggested promoting to policy.

Same attack pattern now blocked in <ms>ms with zero AI cost.
Verified by: <new_eval_case_id>."
git push
```

`ci.yml` runs your regression test on every push from now on. The dogfood
workflow on the next PR auto-applies the rule. Done.

## Pitfalls

- **Regex too greedy** — false positives block legitimate work. The negative
  eval case is your defense. Run `ai-cicd eval` before pushing.
- **Path filter missing** — `diff_contains` alone fires on ANY changed file
  including docs. Always include `paths:` unless the pattern is genuinely
  language-agnostic.
- **`block: true` on uncertain patterns** — only block if there's no
  legitimate use of the pattern, ever. If unsure, use
  `require_human_approval: true` without `block` so a human can override.
- **Promoting AI-quality issues** — if the AI's *reasoning* was wrong (it
  said `request_changes` when it should have said `approve`), the fix is
  in `prompts/`, not `policies/`. Do not promote.
- **Skipping the negative case** — promotes false positives into the system
  with no early warning. Always add at least one.
- **Promoting too early** — one occurrence is not a pattern. Wait for the
  Reflector's explicit suggestion or the 3-occurrence threshold.

## When NOT to promote

| Symptom | Why NOT to promote | Where to fix instead |
|---|---|---|
| AI's reasoning is consistently weak | Pattern isn't deterministic; AI just needs better prompt | `prompts/<agent>.md` |
| Validation rejects when it shouldn't | Validation `post_validate` is too strict | `src/agents/validation.py` |
| Cost is high but verdicts are correct | Right-size the model instead | `policies/model_routing.yaml` |
| Pattern is repo-specific (not general) | Use repo memory, not global policy | `memory/<repo>/pitfalls.md` (auto-managed by Archivist) |

## The flywheel diagram

```
   ┌────────────────────────────────────────────────────────┐
   │                                                        │
   │   AI agents catch new pattern                          │
   │      ↓                                                 │
   │   Reflector suggests rule promotion                    │
   │      ↓                                                 │
   │   Operator (you) reads runbook 05  ← you are here      │
   │      ↓                                                 │
   │   Add rule to policies/risk_rules.yaml                 │
   │      ↓                                                 │
   │   Add positive + negative eval cases                   │
   │      ↓                                                 │
   │   `ai-cicd eval --target policy_engine` passes         │
   │      ↓                                                 │
   │   Commit + push                                        │
   │      ↓                                                 │
   │   ci.yml protects the rule on every future push        │
   │      ↓                                                 │
   │   Future occurrences caught for $0 / <50ms             │
   │      ↓                                                 │
   │   AI free to look for the NEXT pattern  ←──────────┐   │
   │                                                    │   │
   └────────────────────────────────────────────────────┘   │
                       (loop)                               │
```

## Canonical example (referenced in the test corpus)

| Step | File / pipeline | Outcome |
|---|---|---|
| 1. AI catches | `pipe-d58abf94` (PR `Refactor session token validation`) | Security agent flags CWE-347, $0.0612, 84.4s |
| 2. Reflector suggests | same pipeline | `kind: policy_edit, target: policies/risk_rules.yaml` |
| 3. Operator promotes | `policies/risk_rules.yaml:rules[0]` | rule `jwt_none_bypass`, `block: true` |
| 4. Operator extends engine | `src/policy_engine/engine.py:classify` | accepts `diff` param + `match.diff_contains` regex |
| 5. Operator adds tests | `evals/cases/policy__{jwt_none_bypass,docs_only_low,secrets_block}.yaml` | 3/3 pass in 21ms |
| 6. CI gates the test | `.github/workflows/ci.yml:Policy-engine evals` step | red on any future regression |
| 7. Verified | `pipe-05242cca` (same event, after promotion) | $0.00, 0.044s, identical verdict |

Reference these when you're about to promote your second pattern. Same shape.
