# SETUP.md — AI-consumable runbook for deploying AI-CICD to a new repo

> **Audience: an AI assistant (Claude / GPT / Gemini) helping a human deploy
> this AI-CICD pipeline to one of their GitHub repos.** Every step is
> explicit, copy-pasteable, with verification commands and expected output.
>
> If you are a human, you can follow this manually — but the structure is
> optimized for an AI to execute step-by-step.

---

## 0. Read this first (AI: don't skip)

This pipeline reviews PRs / fixes issues with multi-agent orchestration. Before
you do anything:

1. **Confirm working directory** is the cloned `test_cicd` repo, NOT the user's
   target repo. The pipeline lives here; it *reaches out* to the target repo
   via GitHub webhooks.
2. **Never skip git hooks** with `--no-verify` unless the user says so.
3. **Never commit secrets**. If the user pastes an API key, store it via
   `gh secret set`, not in any file.
4. **Always show the user a diff and ask for confirmation** before editing
   `policies/*.yaml` — those YAMLs are *security* config.
5. The "host gateway" runs `claude` + `gemini` CLIs on the host with the
   user's OAuth tokens. Container can't share OAuth — that's by design.

---

## 1. Information you must gather from the user FIRST

Ask the user for these (one short message; don't lecture):

```
1. Target repo: <owner/name>             e.g. acme/payments-api
2. Primary language(s):                  e.g. Python + TypeScript
3. Auth/payment/security-critical paths in their repo:
                                          e.g. src/auth/, services/billing/
4. CI infrastructure paths:               e.g. .github/workflows/, Dockerfile, infra/
5. Trusted committer GitHub usernames:    e.g. huytk, teammate1, dependabot[bot]
6. Webhook strategy:
   (a) ngrok      — fastest, dev-only, URL changes each session
   (b) cloudflared tunnel — free, persistent, recommended for pilot
   (c) VPS + nginx + Let's Encrypt — production-grade
7. Cost ceiling per PR (USD):             default $0.50
8. Provider preference: gemini-default (cheap) or claude-default (better code)
9. Anthropic API key available?           y/n  (needed for dogfood workflow)
```

**If the user is impatient and just gives a repo URL**, autodetect what you
can with `gh repo view <owner/name>` + `gh api repos/<owner/name>/contents/`
and ask only for the must-have items: target repo, trusted committers,
webhook strategy, ANTHROPIC_API_KEY presence.

---

## 2. Preflight checks (run before anything else)

Run these from the `test_cicd` directory. Each must succeed.

```bash
# Tooling — fail loud if any missing
docker version --format '{{.Server.Version}}' || { echo "install Docker Desktop"; exit 2; }
docker compose version | head -1
gh --version | head -1
make --version | head -1
python3 --version
which claude || { echo "install Claude Code CLI: https://docs.claude.com/claude-code"; exit 2; }
which gemini || { echo "install Gemini CLI: npm install -g @google/gemini-cli"; exit 2; }

# Auth — confirm both CLIs work
claude --version
gemini --version            # if errors, fix ~/.gemini/settings.json schema
gh auth status              # must be logged into GitHub

# Repo access — confirm user can read AND write to target repo
gh repo view <OWNER/NAME>                                    # must succeed
gh api repos/<OWNER/NAME>/hooks > /dev/null                  # must succeed → write access
```

If any check fails, STOP and tell the user the exact missing tool. Do not
try to install it yourself unless they explicitly say so.

---

## 3. Phase 1 — Detect repo characteristics (autodetect, don't ask twice)

For the target repo, gather facts the user already published:

```bash
TARGET="<OWNER/NAME>"

# Language — drives test runner choice
gh api repos/$TARGET/languages

# Top-level structure — drives risk_rules paths
gh api repos/$TARGET/contents/ --jq '.[].name'

# CODEOWNERS if any — already lists who reviews what
gh api repos/$TARGET/contents/CODEOWNERS --jq '.content' 2>/dev/null | base64 -d || \
gh api repos/$TARGET/contents/.github/CODEOWNERS --jq '.content' 2>/dev/null | base64 -d || \
echo "no CODEOWNERS"

# Look for auth/payment/security-sensitive paths
for needle in auth login session token jwt payment billing stripe permission; do
  gh api repos/$TARGET/contents/src/$needle 2>/dev/null | jq -r '.path' 2>/dev/null
  gh api repos/$TARGET/contents/services/$needle 2>/dev/null | jq -r '.path' 2>/dev/null
  gh api repos/$TARGET/contents/$needle 2>/dev/null | jq -r '.path' 2>/dev/null
done

# Existing CI — to avoid stomping on it
gh api repos/$TARGET/contents/.github/workflows --jq '.[].name' 2>/dev/null
```

Build a short summary the user can confirm in one yes/no. Example:

> Detected on acme/payments-api:
>   - Language: Python (78%) + TypeScript (22%)
>   - Auth-critical paths: src/auth/, src/payment/, services/billing/
>   - CI workflows present: ci.yml, release.yml — won't conflict
>   - CODEOWNERS exists, 3 trusted reviewers
>
> OK to proceed with these as `policies/risk_rules.yaml` paths?

---

## 4. Phase 2 — Customize policies

Three files to edit. Show the user a diff for each, confirm, then write.

### 4.1 `policies/risk_rules.yaml`

Replace the example paths with the real ones from Phase 1. Pattern:

```yaml
# rule id stays; just change paths to match the target repo
- id: auth_payment_critical
  match:
    paths:
      - "<DETECTED_AUTH_PATH>/**"          # e.g. "src/auth/**"
      - "<DETECTED_PAYMENT_PATH>/**"       # e.g. "src/payment/**"
      - "<DETECTED_BILLING_PATH>/**"       # e.g. "services/billing/**"
      - "<DETECTED_PERMISSION_PATH>/**"
      # keep the catch-all globs:
      - "**/auth/**"
      - "**/payment/**"
  risk_level: critical
  require_human_approval: true
  reason: "Touches authentication, payment, or permissions surface."
```

Keep `secrets_block`, `dependency_high`, `docs_low`, `tests_low` rules
verbatim — they're language-agnostic.

Adjust `ci_infra_high` paths if the repo uses GitLab / CircleCI / something
non-default.

### 4.2 `policies/allowed_authors.yaml`

```yaml
trusted_authors:
  - "<USER_GITHUB_HANDLE>"               # the user
  - "<TEAMMATE_1>"                       # ask user; do not invent
  - "<TEAMMATE_2>"
  - "dependabot[bot]"
  - "renovate[bot]"

trusted_bots:
  - "dependabot[bot]"
  - "renovate[bot]"
```

Untrusted authors get stricter gates (no auto-merge regardless of risk).
Be CONSERVATIVE — empty `trusted_authors` is safer than wrong ones.

### 4.3 `policies/model_routing.yaml`

Two presets the user picks:

**Preset A — Gemini-default (cheap, current default)**: keep the file as-is.

**Preset B — Claude-default (more accurate code, ~3× more expensive)**:
```yaml
default:
  provider: claude
  model:    ""

routing:
  triage:        {provider: gemini, model: ""}    # cheap classify
  documentation: {provider: gemini, model: ""}    # cheap edits
  critic:        {provider: gemini, model: ""}    # different family
  # everything else uses default (claude)
```

Don't override individual agents unless the user has data showing one provider
is better for that agent on their codebase.

---

## 5. Phase 3 — Auth & secrets

```bash
# 5.1 Generate a strong webhook secret (one-time, never rotate without
# re-configuring GitHub at the same time)
SECRET=$(openssl rand -hex 32)
echo "AICICD_WEBHOOK_SECRET=$SECRET" >> .env

# 5.2 Tell the user to save the secret somewhere safe (1Password / Vault).
# Display once, never print again.
echo "Webhook secret: $SECRET"
echo "Save this in your password manager NOW."

# 5.3 Set GitHub repo secrets for the dogfood workflow
gh secret set ANTHROPIC_API_KEY -R <OWNER/NAME>          # asks for value, paste it
gh secret set AICICD_WEBHOOK_SECRET -R <OWNER/NAME> --body "$SECRET"
```

Confirm:
```bash
gh secret list -R <OWNER/NAME>           # must show both names
```

Append cost / concurrency tunables to `.env`:
```bash
cat >> .env <<EOF
AICICD_PIPELINE_BUDGET_USD=0.50
AICICD_WORKER_CONCURRENCY=2
AUTO_APPROVE=false
AICICD_LOG_FORMAT=json
EOF
```

`AUTO_APPROVE=false` MUST stay false in any real environment.

---

## 6. Phase 4 — Webhook ingress

Pick the option the user chose in step 1.

### 6a. Cloudflare Tunnel (recommended for pilot)

```bash
# Install once
brew install cloudflared
cloudflared tunnel login                  # opens browser

# Persistent tunnel — survive reboots, fixed URL
cloudflared tunnel create ai-cicd
cloudflared tunnel route dns ai-cicd ai-cicd.<USER_DOMAIN>
cloudflared tunnel run ai-cicd --url http://localhost:8000 &
```

Note the URL it prints (e.g. `https://ai-cicd.user.com`).

### 6b. ngrok (dev only, URL changes each session)

```bash
ngrok http 8000
# Copy the https://*.ngrok-free.app URL it prints
```

### 6c. VPS

Out of scope for this runbook. User must front pipeline:8000 with nginx +
Let's Encrypt; webhook URL becomes `https://ai-cicd.<their-domain>`.

### 6.x — Configure GitHub webhook

```bash
WEBHOOK_URL="https://<your-tunnel-url>/event/github"

gh api -X POST repos/<OWNER/NAME>/hooks \
  -f name=web \
  -f active=true \
  -f config[url]=$WEBHOOK_URL \
  -f config[content_type]=json \
  -f config[secret]=$SECRET \
  -f config[insecure_ssl]=0 \
  -f 'events[]=pull_request' \
  -f 'events[]=issues' \
  -f 'events[]=issue_comment'
```

Verify the hook was created and is reachable:

```bash
gh api repos/<OWNER/NAME>/hooks --jq '.[] | {url: .config.url, last_response: .last_response}'
```

---

## 7. Phase 5 — Boot the stack

```bash
# Start the host-side gateway (claude + gemini CLIs).
# Runs in background; pidfile at /tmp/ai-cicd-gateway.pid.
make gateway

# Verify gateway healthy
curl -sf http://localhost:8200/readyz
# Expected: {"status":"ready","claude":true,"gemini":true}

# Start the pipeline container.
make up
# Expected: container ai-cicd-pipeline created, /readyz returns 200

# Both healthy?
make ready
# Expected:
#   gateway:  {"status":"ready","claude":true,"gemini":true}
#   pipeline: {"status":"ready"}
```

If `claude=false`: user needs to `claude /login` once.
If `gemini=false`: check `~/.gemini/settings.json` (no `name`/`transport` keys
under `mcpServers.*` — they're invalid in current Gemini CLI version).

---

## 8. Phase 6 — Smoke test (BEFORE wiring webhook)

Run all deterministic gates first. They MUST all pass:

```bash
make trifecta-audit              # → "No lethal-trifecta agents." exit 0
ai-cicd eval --target policy_engine
# Expected: 3/3 cases passed (jwt_none_bypass, docs_only_low, secrets_block)
```

Then drive a synthetic event through the webhook to confirm end-to-end:

```bash
# Create a tiny test event matching the user's repo
cat > /tmp/test_event.json <<EOF
{
  "kind": "pull_request",
  "action": "opened",
  "repo": "<OWNER/NAME>",
  "number": 1,
  "title": "Test: AI-CICD smoke test",
  "body": "Synthetic event to verify pipeline wiring.",
  "author": "<USER_GITHUB_HANDLE>",
  "branch": "test/ai-cicd",
  "base_branch": "main",
  "files_changed": ["README.md"],
  "diff": "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@\n+test line\n",
  "labels": []
}
EOF

# POST through the LOCAL webhook (HMAC verified)
SIG="sha256=$(openssl dgst -sha256 -hmac "$SECRET" < /tmp/test_event.json | awk '{print $2}')"
curl -sf -X POST http://localhost:8000/event/demo \
     -H "X-Aicicd-Signature: $SIG" \
     -H "Content-Type: application/json" \
     --data @/tmp/test_event.json

# Expected: {"accepted":true,"pipeline_id":"pipe-..."}
```

Wait for processing (~1-2 min for low-risk PR), then:

```bash
make audit PIPELINE_ID=<pipeline_id_from_response>
# Should show: triage → security_scan → code_review → validation → critic
# All `agent_done success`. No `agent_failed`.

make cost PIPELINE_ID=<pipeline_id_from_response>
# Should show 5 agents, total cost roughly $0.03 - $0.10.
```

If anything fails, STOP and consult `runbooks/01_provider_down.md` etc.

---

## 9. Phase 7 — First real PR

Tell the user to:
1. Open a small docs-only PR on the target repo (e.g. `README.md` typo fix).
2. Watch the AI-CICD comment appear within ~1-2 min (a single `<!-- ai-cicd-review -->`-tagged comment).
3. Verify the comment shows: per-agent status, cost, link to audit.

If the comment doesn't appear within 5 min:
```bash
# Check the GitHub webhook delivered
gh api repos/<OWNER/NAME>/hooks/<hook_id>/deliveries --jq '.[0]'

# Check pipeline received it
make logs | grep pipeline_start
```

---

## 10. Phase 8 — First-week monitoring

Have the user check these every morning for the first 7 days:

```bash
# Daily cost
sqlite3 logs/audit.db "
  SELECT date(ts, 'unixepoch') AS day, COUNT(DISTINCT pipeline_id) AS pipelines,
         SUM(json_extract(payload_json, '\$.telemetry.cost_usd')) AS cost_usd
  FROM audit
  WHERE action='agent_done' AND ts > strftime('%s','now','-7 days')
  GROUP BY day ORDER BY day"

# Pipelines that took > 3 min — likely stuck or context-bloated
sqlite3 logs/audit.db "
  SELECT pipeline_id, MAX(ts) - MIN(ts) AS sec
  FROM audit GROUP BY pipeline_id HAVING sec > 180 ORDER BY sec DESC"

# Repeated root causes — promote to deterministic rule
ai-cicd memory <OWNER/NAME>
```

After 1-2 weeks, if a root cause appears 3+ times, follow
`runbooks/05_pattern_promotion.md`.

---

## 11. Failure handling (common issues)

| Symptom | Likely cause | Fix |
|---|---|---|
| Webhook deliveries show 401 | secret mismatch | Re-set both `.env` AND GitHub hook with same value |
| `gateway: gemini=false` | gemini settings.json schema | Remove invalid `name` / `transport` keys under `mcpServers.*` |
| `gateway: claude=false` after restart | OAuth expired | `claude /login` on host (not in container) |
| Pipeline `final_status: failed` repeatedly | agent JSON malformed | Check provider — may need `AICICD_FORCE_PROVIDER=claude` for now |
| 429 from webhook | queue full | Increase `AICICD_WORKER_CONCURRENCY` |
| Cost spike | wrong model routed for cheap task | `make providers` and audit `policies/model_routing.yaml` |
| Pipeline runs but no comment posted | GitHub auth missing | Check `gh auth status`; tool_proxy needs gh CLI |

---

## 12. What stays repo-agnostic (DO NOT touch)

These files are tested, audited, and shouldn't be edited per-repo:

- `src/agents/*.py`
- `src/orchestrator/*.py`
- `src/policy_engine/engine.py`
- `src/llm/*.py`
- `src/server/webhook.py`
- `src/audit/*.py`
- `prompts/*.md` — system prompts; edit only via the prompt-promotion procedure
- `schemas/*.json` — output contracts
- `runbooks/*.md` — operational SOPs
- `evals/harness.py`

---

## 13. AI assistant — what to do at the end

After Phase 7 succeeds, send the user a single message with:

1. Link to the test PR + comment screenshot (or quote of the comment).
2. The `pipeline_id` of the smoke-test run.
3. A 3-line "what to watch for the first week" reminder.
4. A reference to `runbooks/05_pattern_promotion.md` for when AI catches
   the same pattern repeatedly.
5. Offer to: (a) check in after 7 days with metrics summary, OR
   (b) help adapt to a second repo, OR (c) close out.

Do not oversell. Be honest about the 8 known production gaps documented
in `README.md` (in-memory queue, no per-pipeline timeout, no multi-tenancy
isolation, etc.). The user's pilot will surface which ones matter.

---

## 14. Adapt-to-repo template (for AI to fill in)

When the user gives `<OWNER/NAME>` and codebase facts, produce these
filled-in artifacts BEFORE running any `gh secret set` command:

```
[ ] policies/risk_rules.yaml      — paths replaced with detected ones
[ ] policies/allowed_authors.yaml — trusted_authors list
[ ] policies/model_routing.yaml   — preset A or B confirmed
[ ] .env                           — webhook secret + budget + concurrency
[ ] examples/<repo>_smoke.json    — synthetic event matching the repo
[ ] webhook URL chosen + tested
```

Show the diffs for the policies files first. Get the user's "ok" before
applying them. Once applied, proceed through Phases 5–8 in order.

If something is unclear about the user's codebase, ASK ONE QUESTION at a
time. Do not guess auth paths — wrong paths in `risk_rules.yaml` mean
either over-blocking (bad for velocity) or under-blocking (bad for security).
