# Deploy AI-CICD to a new project — step-by-step (Docker)

> **Audience: human operator** who wants to use this AI-CICD pipeline to
> review PRs on **a different GitHub repo** (not this one).
>
> This is the hands-on Docker tutorial. For the AI-readable version of the
> same procedure, see [SETUP.md](SETUP.md). For the spec wiring of this
> exact repo, see [PILOT_SETUP.md](PILOT_SETUP.md).

You'll end up with:

- AI-CICD pipeline (Docker) running on your laptop / VPS
- Cloudflared tunnel exposing it to the public internet
- GitHub webhook on your target repo posting events to the pipeline
- Real review comments appearing on every PR within 1–3 minutes

Total time: **45–75 minutes** the first time. ~15 minutes for subsequent repos.

---

## 0. Prerequisites

Install once on the host that will run the pipeline:

```bash
# macOS (adjust for Linux)
brew install docker docker-compose gh cloudflared
brew install --cask docker            # Docker Desktop
npm install -g @anthropic-ai/claude-code @google/gemini-cli

# Verify
docker version --format '{{.Server.Version}}'    # ≥ 24
docker compose version | head -1                  # v2+
gh --version                                       # ≥ 2.40
cloudflared --version                              # ≥ 2024
claude --version                                   # ≥ 1.x
gemini --version                                   # ≥ 0.40
```

**Authenticate the CLIs (one-time, OAuth):**

```bash
claude         # opens browser for OAuth, creates ~/.claude.json
gemini         # opens browser, creates ~/.gemini/
gh auth login  # GitHub OAuth or PAT; pick the account that owns the target repo
```

---

## 1. Clone this repo and check out a working copy

```bash
git clone https://github.com/Jackerha1/test_cicd ai-cicd
cd ai-cicd
git checkout develop                  # latest pipeline source
```

> Don't fork unless you plan to upstream changes. The pipeline is
> orchestration that runs against any repo via webhook — no need to
> embed it inside the target repo's source tree.

---

## 2. Gather facts about the target repo

Before you edit any policy file, write down (or autodetect via `gh`):

| Item | How to find |
|---|---|
| **Repo full name** | `gh repo view --json nameWithOwner` |
| **Languages** | `gh api repos/$REPO/languages` |
| **Auth-critical paths** | `gh api repos/$REPO/contents/ \| grep -i 'auth\|login\|jwt\|session\|payment'` |
| **CI infra paths** | check `.github/workflows`, `Dockerfile`, `infra/`, `deploy/` |
| **Trusted committer logins** | `gh api repos/$REPO/contributors --jq '.[].login'` |
| **Existing webhooks** | `gh api repos/$REPO/hooks` |

Replace `$REPO` with `your-org/your-repo`.

---

## 3. Customize policies for your target repo

Three YAML files. Show diffs to your team before merging.

### `policies/risk_rules.yaml`

Replace the example paths with your repo's real critical surfaces:

```yaml
- id: auth_payment_critical
  match:
    paths:
      - "src/auth/**"            # ← replace with your auth dir
      - "services/billing/**"    # ← your payment dir
      - "internal/permissions/**"
  risk_level: critical
  require_human_approval: true
  reason: "Touches authentication, payment, or permissions surface."
```

Keep `secrets_block`, `dependency_high`, `docs_low`, `tests_low`,
`jwt_none_bypass` rules verbatim — they're language-agnostic and battle-tested.

### `policies/allowed_authors.yaml`

```yaml
trusted_authors:
  - "your-github-username"
  - "your-teammate-1"
  - "your-teammate-2"
  - "dependabot[bot]"
  - "renovate[bot]"

trusted_bots:
  - "dependabot[bot]"
```

**Be conservative.** An empty `trusted_authors` is safer than wrong ones.

### `policies/model_routing.yaml` (optional)

Default routes most agents to **gemini** with **claude** for the critic
(different family). Keep this unless you have eval data showing otherwise.

---

## 4. Configure secrets

Create `.env` (gitignored):

```bash
# AI-CICD core
CLAUDE_CLI_API_URL=http://host.docker.internal:8200
WORKSPACE_DIR=/app/artifacts
AUDIT_DB_PATH=/app/logs/audit.db
SANDBOX_MODE=subprocess
MAX_AGENT_RETRIES=2
AUTO_APPROVE=false                                 # NEVER true in real env
AICICD_LOG_FORMAT=json
AICICD_WORKER_CONCURRENCY=2
AICICD_PIPELINE_BUDGET_USD=0.50                    # tighter for pilot

# Generated secrets — fill these in
AICICD_WEBHOOK_SECRET=                             # openssl rand -hex 32
GITHUB_TOKEN=                                      # gh auth token
```

Populate the bottom two:

```bash
echo "AICICD_WEBHOOK_SECRET=$(openssl rand -hex 32)" >> .env
echo "GITHUB_TOKEN=$(gh auth token)" >> .env
```

Save `AICICD_WEBHOOK_SECRET` in 1Password / Vault — you'll need it again
when configuring the GitHub webhook.

> **Security**: do not paste this `.env` anywhere. The `gh auth token` is a
> live credential. If you accidentally expose it, rotate immediately:
> `gh auth refresh` or `gh auth logout && gh auth login`.

---

## 5. Build and start the Docker stack

The pipeline has two pieces: the **gateway** runs on the *host* (so the
`claude` and `gemini` CLIs can use your machine's OAuth tokens), and the
**pipeline container** runs in Docker.

### 5a. Start the host-side gateway

```bash
make gateway
```

This wraps the `claude` and `gemini` CLIs behind `http://localhost:8200`.

```bash
curl -fsS http://localhost:8200/readyz
# Expected: {"status":"ready","claude":true,"gemini":true}
```

If `claude=false` or `gemini=false`, your CLI auth has expired. Re-run
`claude` / `gemini` to refresh OAuth.

### 5b. Build and start the pipeline container

```bash
make build      # ~2-3 min the first time (npm + python deps)
make up         # starts the pipeline container with healthcheck
```

```bash
make ready
# Expected:
#   gateway:  {"status":"ready","claude":true,"gemini":true}
#   pipeline: {"status":"ready"}
```

If the pipeline can't reach the gateway, `host.docker.internal` is not
resolving. The `docker-compose.yml` already maps it for Linux via
`extra_hosts`. Macs / Docker Desktop have it built in.

### 5c. Smoke-test deterministic gates

```bash
ai-cicd trifecta-audit
ai-cicd eval --target policy_engine
```

Both should pass with no surprises.

---

## 6. Expose the pipeline (cloudflared tunnel)

The pipeline lives on your laptop on port 8000. GitHub needs a public URL.
Cloudflared gives you one for free without a domain or static IP.

### 6a. Quick tunnel (fastest; URL changes each session)

```bash
cloudflared tunnel --url http://localhost:8000 --protocol http2 &
```

Watch the output — you'll see something like:

```
Your quick Tunnel has been created! Visit it at:
  https://aged-pony-saturday-aicicd.trycloudflare.com
```

Copy that URL.

> The `--protocol http2` flag forces TCP fallback if your network
> blocks UDP/QUIC. If your network allows QUIC, you can drop it for
> ~10% lower latency.

### 6b. Persistent tunnel (recommended for serious pilot)

```bash
cloudflared tunnel login                   # opens browser
cloudflared tunnel create ai-cicd
cloudflared tunnel route dns ai-cicd ai-cicd.<your-domain>
cloudflared tunnel run ai-cicd --url http://localhost:8000
```

Now the URL is `https://ai-cicd.<your-domain>` and survives reboots.

### 6c. VPS / production

Skip cloudflared. Run the same `make gateway && make up` on a small VPS,
front the pipeline with nginx + Let's Encrypt at a stable domain.

---

## 7. Configure the GitHub webhook

```bash
SECRET=$(grep ^AICICD_WEBHOOK_SECRET= .env | cut -d= -f2)
TUNNEL_URL=https://aged-pony-saturday-aicicd.trycloudflare.com   # ← your URL
REPO=your-org/your-repo

gh api -X POST "repos/$REPO/hooks" \
  -f name=web \
  -F active=true \
  -F "config[url]=$TUNNEL_URL/event/github" \
  -F "config[content_type]=json" \
  -F "config[secret]=$SECRET" \
  -F "config[insecure_ssl]=0" \
  -F "events[]=pull_request" \
  -F "events[]=issues" \
  -F "events[]=issue_comment"

# Save the webhook id — you'll need it to update or delete later
gh api "repos/$REPO/hooks" --jq '.[].id'
```

### Smoke-test the webhook end-to-end

```bash
SECRET=$(grep ^AICICD_WEBHOOK_SECRET= .env | cut -d= -f2)
BODY='{"action":"opened","pull_request":{"number":1,"title":"smoke","body":"","user":{"login":"you"},"head":{"ref":"x"},"base":{"ref":"main"}},"repository":{"full_name":"'$REPO'"}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"

curl -sf -X POST "$TUNNEL_URL/event/github" \
     -H "X-Hub-Signature-256: $SIG" \
     -H "X-GitHub-Event: pull_request" \
     -H "Content-Type: application/json" \
     -d "$BODY"
# Expected: {"accepted":true,"pipeline_id":"pipe-..."}
```

If you get `{"detail":"bad signature"}`, the secret in `.env` and the
webhook config diverged. Rotate both:

```bash
NEW=$(openssl rand -hex 32)
sed -i '' "s|^AICICD_WEBHOOK_SECRET=.*|AICICD_WEBHOOK_SECRET=$NEW|" .env
make restart
gh api -X PATCH "repos/$REPO/hooks/<HOOK_ID>" -F "config[secret]=$NEW"
```

---

## 8. Branch protection (optional but recommended)

Lock `main` so the pipeline can't accidentally merge into it:

```bash
gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["static-gates"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
```

Also create a `develop` branch where the pipeline reviews PRs:

```bash
gh api -X POST "repos/$REPO/git/refs" \
  -f ref="refs/heads/develop" \
  -f sha="$(gh api repos/$REPO/git/refs/heads/main --jq .object.sha)"
```

---

## 9. Open the first real PR

Pick an existing branch on the target repo, or create a small PR there:

```bash
# In the target repo's local clone
git checkout -b test/ai-cicd
echo "test" >> README.md
git add README.md
git commit -m "test: AI-CICD review smoke"
git push origin test/ai-cicd
gh pr create --base develop --title "test: AI-CICD review smoke" --body "Triggers the pipeline."
```

Within 1–3 minutes:

1. `dogfood-pr-review.yml` workflow posts a "review queued" comment.
2. The local pipeline receives the webhook, fetches the diff, runs all
   agents, and **replaces the queued comment** with a real review.
3. The audit log fills up (`make audit PIPELINE_ID=pipe-...`).

If no review appears within 5 minutes:

- `./scripts/pilot.sh status` — is everything up?
- `make logs` — pipeline logs (NDJSON; `jq` it)
- GitHub repo Settings → Webhooks → Recent Deliveries → check status code

---

## 10. Daily ops

| Task | Command |
|---|---|
| Start everything | `./scripts/pilot.sh up` |
| Stop everything | `./scripts/pilot.sh down` |
| Status + health | `./scripts/pilot.sh status` |
| Restart cleanly | `./scripts/pilot.sh restart` |
| Pipeline logs | `make logs` |
| Audit a run | `make audit PIPELINE_ID=pipe-...` |
| Cost forensics | `make cost PIPELINE_ID=pipe-...` |
| Per-repo memory | `make memory REPO=owner/name` |

---

## 11. First-week monitoring

For the first 7 days, check daily:

```bash
# How much you spent today
sqlite3 logs/audit.db "
  SELECT COUNT(DISTINCT pipeline_id) AS pipelines,
         SUM(json_extract(payload_json, '\$.telemetry.cost_usd')) AS cost
  FROM audit
  WHERE action='agent_done'
    AND ts > strftime('%s','now','-1 day')"

# Repeated root causes — promotion candidates
sqlite3 logs/audit.db "
  SELECT json_extract(payload_json, '\$.root_cause') AS rc, COUNT(*) AS n
  FROM audit
  WHERE action='root_cause' AND ts > strftime('%s','now','-7 days')
  GROUP BY rc HAVING n >= 3 ORDER BY n DESC"
```

If a root cause appears 3+ times in a week, follow
[runbooks/05_pattern_promotion.md](runbooks/05_pattern_promotion.md) to
ratchet it into a deterministic rule.

---

## 12. Going production-grade

Local Docker + cloudflared is fine for a single-team pilot. When you
outgrow it:

| Need | Upgrade path |
|---|---|
| 24/7 uptime regardless of laptop state | Move gateway + pipeline to a small VPS |
| Multi-instance pipeline | Replace `asyncio.Queue` with Redis Streams |
| OAuth tokens not portable to cloud | Use Anthropic API key + Google API key on VPS |
| Cross-service tracing | Add OpenTelemetry instrumentation |
| Compliance / encryption at rest | SQLCipher for `audit.db`, encrypted volume |
| Multi-tenant fairness | Per-tenant queue + token bucket |

Each is incremental — none required for the pilot. See the README's "8
known production gaps" section for prioritization signal.

---

## 13. Troubleshooting cheatsheet

| Symptom | Probable cause | Fix |
|---|---|---|
| Webhook 401 | secret mismatch | `make restart` after re-syncing `.env` and webhook |
| `gateway: claude=false` | OAuth expired | `claude` to re-login on the host |
| `gateway: gemini=false` | invalid `~/.gemini/settings.json` | remove unrecognized keys (gemini errors print which ones) |
| Pipeline `final_status: failed` | agent JSON parsing | `make audit PIPELINE_ID=pipe-...` to see which agent + retry count |
| Pipeline reviews never post | container claude needs OAuth | only `make gateway` (host) has OAuth — restart it |
| Cost spike | wrong model routed | check `make providers`; tune `policies/model_routing.yaml` |
| Same false positive over and over | rule promotion needed | follow `runbooks/05_pattern_promotion.md` |
| Comment posted twice on PR | broken `<!-- ai-cicd-review -->` marker | check `src/tool_proxy/tools.py` |

For deeper failure modes see [runbooks/00_index.md](runbooks/00_index.md).

---

## 14. What stays repo-agnostic (don't edit per-deploy)

- `src/agents/*.py`, `src/orchestrator/*.py`, `src/policy_engine/engine.py`,
  `src/llm/*.py`, `src/server/webhook.py`, `src/audit/*.py`
- `prompts/*.md`, `schemas/*.json`
- `runbooks/*.md`
- `evals/harness.py`

If you find yourself editing one of these to deploy to a new repo, you're
probably patching where you should be configuring. Stop and ask "is there
a YAML / env / policy I'm missing?"
