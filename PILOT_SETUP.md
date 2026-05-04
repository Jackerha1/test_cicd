# PILOT_SETUP.md — Wire AI-CICD pipeline → Jackerha1/test_cicd

> **Purpose**: connect the GitHub repo at https://github.com/Jackerha1/test_cicd
> to the AI-CICD pipeline running on the maintainer's host. This document is
> for the **maintainer** (HuyTK) — execute commands top-to-bottom.

## Topology

```
   GitHub repo (Jackerha1/test_cicd)
   ├── main      ← sacred, AI-CICD pipeline source
   └── develop   ← CRUD demo work; PRs land here, AI-CICD reviews

         │ webhook (HMAC-verified)
         ▼
   cloudflared tunnel (https://<your-name>.trycloudflare.com)
         │
         ▼
   localhost:8000 (pipeline container — make up)
         │ HTTP /chat
         ▼
   localhost:8200 (claude-cli-api gateway — make gateway)
         │
         ├── claude CLI  (host OAuth — ~/.claude.json)
         └── gemini CLI  (host OAuth — ~/.gemini/)
```

`main` never receives PRs from `develop` — the policy is enforced both by
GitHub branch protection (below) AND by reviewer convention.

---

## Step 1 — Branch protection on main

Run **once** after `gh auth status` shows you're logged in.

```bash
REPO="Jackerha1/test_cicd"

# Protect main: require PR + reviews + status checks; block force-push & deletion.
# Note: the AI-CICD pipeline never opens PRs into main, so this is a hard wall.
gh api -X PUT repos/$REPO/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "static-gates"
    ]
  },
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

# Verify
gh api repos/$REPO/branches/main/protection --jq '.url' && echo "main protected ✓"
```

Optional — softer protection on `develop` so the dogfood comment still posts:

```bash
gh api -X PUT repos/$REPO/branches/develop/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["static-gates"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

---

## Step 2 — Install cloudflared (one-time)

```bash
# macOS
brew install cloudflared

# Verify
cloudflared --version
```

---

## Step 3 — Generate webhook secret + start local stack

```bash
cd /Users/huytk/Documents/build_app/CICD_TEST/test_cicd

# Generate strong secret (one-time; SAVE in 1Password)
openssl rand -hex 32 > /tmp/aicicd-webhook-secret
cat /tmp/aicicd-webhook-secret              # copy to clipboard now

# Inject into .env
SECRET=$(cat /tmp/aicicd-webhook-secret)
grep -q AICICD_WEBHOOK_SECRET .env || echo "AICICD_WEBHOOK_SECRET=$SECRET" >> .env
sed -i '' "s|^AICICD_WEBHOOK_SECRET=.*|AICICD_WEBHOOK_SECRET=$SECRET|" .env

# Start the host gateway (claude + gemini CLI behind /chat on :8200)
make gateway

# Start the pipeline container (webhook server on :8000, queue, audit, etc.)
make up

# Verify both green
make ready
# Expected:
#   gateway:  {"status":"ready","claude":true,"gemini":true}
#   pipeline: {"status":"ready"}
```

---

## Step 4 — Cloudflared tunnel (foreground for now)

In a NEW terminal (keep it running):

```bash
cloudflared tunnel --url http://localhost:8000
```

Note the URL it prints. Looks like:

```
https://aged-pony-saturday-aicicd.trycloudflare.com
```

Save this URL — you'll paste it into the GitHub webhook config.

> **For persistent tunnels** (URL doesn't change on restart), see
> https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/

---

## Step 5 — Configure GitHub webhook

```bash
TUNNEL_URL="https://<paste-from-step-4>"
SECRET=$(cat /tmp/aicicd-webhook-secret)
REPO="Jackerha1/test_cicd"

gh api -X POST repos/$REPO/hooks \
  -f name=web \
  -f active=true \
  -F config[url]="$TUNNEL_URL/event/github" \
  -F config[content_type]=json \
  -F config[secret]="$SECRET" \
  -F config[insecure_ssl]=0 \
  -F 'events[]=pull_request' \
  -F 'events[]=issues' \
  -F 'events[]=issue_comment'

# Verify
gh api repos/$REPO/hooks --jq '.[] | {url: .config.url, last_response: .last_response}'
```

You should see your tunnel URL. `last_response.code: 0` is normal (no event yet).

---

## Step 6 — Smoke test the webhook

```bash
SECRET=$(cat /tmp/aicicd-webhook-secret)
BODY='{"action":"opened","pull_request":{"number":1,"title":"test","body":"","user":{"login":"HuyTK"},"head":{"ref":"x"},"base":{"ref":"develop"}},"repository":{"full_name":"Jackerha1/test_cicd"}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"

curl -sf -X POST "$TUNNEL_URL/event/github" \
     -H "X-Hub-Signature-256: $SIG" \
     -H "X-GitHub-Event: pull_request" \
     -H "Content-Type: application/json" \
     -d "$BODY"

# Expected: {"accepted":true,"pipeline_id":"pipe-..."}
```

If you get `{"detail":"bad signature"}`, the secret in `.env` doesn't match
the secret in GitHub. Rotate both.

---

## Step 7 — Open the first real PR

The feature branch already exists: `feature/crud-demo-skeleton`. Push it
and open a PR to `develop`:

```bash
cd /Users/huytk/Documents/build_app/CICD_TEST/test_cicd
git push origin feature/crud-demo-skeleton
# pre-push hook will prompt — answer y

gh pr create \
  --base develop \
  --head feature/crud-demo-skeleton \
  --title "feat(crud-demo): Tasks API + UI scaffold" \
  --body "Initial CRUD demo (Flask + SQLAlchemy + JWT + React). 27/27 tests passing locally. AI-CICD pipeline reviews this PR."
```

Within 1–3 min:
1. The "review queued" comment appears (from `dogfood-pr-review.yml`).
2. The local pipeline receives the webhook → runs all agents → posts a real
   review comment that **replaces the queued one**.
3. The `crud-demo tests` workflow runs pytest + vitest in CI as a parallel
   deterministic gate.

---

## Daily ops

| Task | Command |
|---|---|
| Start everything | `make gateway && make up && cloudflared tunnel --url http://localhost:8000` |
| Check ready | `make ready` |
| See pipeline logs (NDJSON) | `make logs` |
| Audit a run | `make audit PIPELINE_ID=pipe-...` |
| Cost forensics | `make cost  PIPELINE_ID=pipe-...` |
| Stop pipeline | `make down` |
| Stop gateway too | `make down-all` |

---

## Known limits (be honest with PR authors)

The pipeline only reviews PRs while:
- The host machine is on
- `make gateway` + `make up` are running
- Cloudflared tunnel is up

If any of those are off, GitHub webhooks queue at GitHub for ~24h then drop.
PR author sees only the "review queued" comment with no follow-up.

For 24/7 reviews, move the gateway to a small VPS with API-key auth instead
of host OAuth. That's the v3 production deployment — see runbooks/.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Webhook 401 in GitHub deliveries page | Secret mismatch — re-set both `.env` and GitHub hook |
| Webhook `Couldn't reach the server` | Tunnel down, or pipeline not running |
| "Review queued" comment but no real review | Check `make logs` — gateway/pipeline crashed? |
| Real review comment never replaces queued | Pipeline's `scripts/post_pr_review.py` failed (see audit) |
| Pipeline blocks on auth/JWT change | Working as designed — runbook 03 explains, runbook 05 to promote |

See `runbooks/` for full failure-mode procedures.
