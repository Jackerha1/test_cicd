# AI-Powered CI/CD

> **v4 — Production deployment**: Dockerized 2-service stack (gateway +
> pipeline), HMAC-verified webhook + bounded worker queue, NDJSON logs,
> `/healthz`+`/readyz`, per-pipeline cost ceiling, `Makefile` ops surface,
> [runbooks](runbooks/00_index.md) for failure modes + the
> [pattern-promotion SOP](runbooks/05_pattern_promotion.md) (AI signal → deterministic rule).
> Provider stack: **Claude CLI + Gemini CLI** behind the single
> `claude-cli-api` gateway. See [v4 section](#v4--production-deployment).
>
> **v3 — Karpathy at OpenAI**: provider-agnostic LLM layer, per-agent model
> routing, structured outputs, `ai-cicd compare` for eval-driven provider
> selection. See [v3 section](#v3--karpathy-at-openai).
>
> **v2 — Karpathy lens applied**: eval harness, token/cost telemetry, Critic
> + Reflector agents, per-repo memory, LLM-OS parallel kernel, lethal-trifecta
> auditor, data flywheel. See [v2 section](#v2--karpathy-style-extensions).


A multi-agent CI/CD pipeline that processes GitHub-style issues, pull requests
and comments through 9 specialised agents — **inside a hardened control
hallway**: deterministic policy gates, scope enforcement, secret redaction,
output validation, human approval for risky actions, and an immutable audit
log of everything.

> **Core thesis** — AI agents are non-deterministic. CI/CD outcomes must be
> deterministic. So we **contain** rather than *trust*: agents only get the
> minimum context, the minimum tools, and every output is checked.

## Architecture (6 layers)

```
GitHub event ──► Trigger ──► Auth/Permission
                              │
                              ▼
                        Context Builder ──── (redacts secrets)
                              │
                              ▼
                        Policy Engine (deterministic, YAML)
                              │
                              ▼
                        Orchestrator (PR-review or Auto-fix flow)
                              │
            ┌────────────┬────┴─────┬───────────┬───────────┐
            ▼            ▼          ▼           ▼           ▼
         Triage      Planner     Bug Fix    Test Writer   Docs
            │                                 │
            └─────────────► Sandbox + Test Runner
                              │
                              ▼
                        Security Scan ──► Code Review
                              │
                              ▼
                        Validation (final cross-check)
                              │
                              ▼
                        Tool Proxy ◄── Human Approval Gate
                              │
                              ▼
                  push_branch / open_pr / merge / deploy
                              │
                              ▼
                  Deployment Agent (staging→canary→full)
                              │
                              ▼
                  Immutable Audit Log (SQLite)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Quick start

### 1. Start the Claude CLI API server

The pipeline talks to Claude through the local FastAPI in `claude-cli-api/`:

```bash
cd claude-cli-api
PLANNER_BACKEND=claude uvicorn main:app --port 8765
```

Probe it works (in another terminal):

```bash
curl http://localhost:8765/health
```

### 2. Install the pipeline

```bash
cd ..
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # tweak if needed
```

### 3. Run the pipeline

```bash
# List sample events
ai-cicd list

# Run the auto-fix flow against an issue
ai-cicd run examples/issue_login_bug.json

# Run the PR-review flow against a PR
ai-cicd run examples/pr_auth_change.json

# This one is REJECTED by policy (touches .env)
ai-cicd run examples/pr_secrets_attempt.json
```

After each run:

```bash
ai-cicd audit <pipeline_id>      # the immutable trail
cat logs/<pipeline_id>.json      # the structured result
```

## The 9 Agents

| # | Agent             | Role                                              | Writes code? | Approves anything? |
|---|-------------------|---------------------------------------------------|--------------|---------------------|
| 1 | **Triage**        | Classify event (kind/severity/scope)              | No           | No                  |
| 2 | **Planner**       | Build task graph + `allowed_paths` boundary       | No           | No                  |
| 3 | **Bug Fix**       | Smallest unified-diff patch                       | Yes (branch) | No                  |
| 4 | **Test Writer**   | Tests that fail if bug returns                    | Yes (branch) | No                  |
| 5 | **Security Scan** | OWASP / secrets / supply-chain risk               | No           | No                  |
| 6 | **Code Review**   | Logic, scope creep, conventions                   | No           | No                  |
| 7 | **Documentation** | README/CHANGELOG/docs updates                     | Yes (docs)   | No                  |
| 8 | **Validation**    | **Final** cross-check; deterministic post-rules   | No           | Bundle only, never merges |
| 9 | **Deployment**    | Staged rollout (staging→canary→full)              | No           | Never prod without human |

Each agent has:
- a system prompt at `prompts/<name>.md`
- a JSON output schema at `schemas/<name>.json`
- a Python class at `src/agents/<name>.py` (with deterministic `post_validate`)
- a Claude Code subagent at `.claude/agents/<name>-agent.md`

## What protects you

| Threat                               | Defense                                                                                  |
|--------------------------------------|------------------------------------------------------------------------------------------|
| Prompt injection in issue body       | Body labeled UNTRUSTED in context; Triage flags it; secrets pre-redacted                 |
| Secret leak                          | Context Builder regex-redacts; `.env*` files blocked at policy layer                     |
| Patch sneaks outside requested scope | Planner sets `allowed_paths`; Bug Fix `post_validate` rejects; Validation re-checks      |
| Test theatre (`assert True`)         | Test Writer `post_validate` rejects empty/meaningless asserts                            |
| Agent claims tests pass              | Real test runner output required; Validation rejects `synthetic: true`                   |
| Agent vouches for its own work       | Validation Agent is an independent step with its own hard checks                         |
| Risky action under guise of safe one | Tool Proxy + Policy Engine: `(agent, action, risk_level) → auto/approval/forbidden`      |
| Deploy to prod without sign-off      | Approval Matrix forbids prod for high/critical risk; staged rollout mandatory            |
| Infinite agent retry loop            | `MAX_AGENT_RETRIES=2` per agent, then surface to human                                   |
| "Who approved this?"                 | Append-only SQLite audit log, every step                                                 |

## Layout

```
prompts/         9 system prompts (one per agent)
schemas/         9 JSON output schemas
policies/        risk_rules.yaml  approval_matrix.yaml  allowed_authors.yaml
src/
  trigger/       webhook receiver (file-based for MVP)
  auth/          permission check
  context/       context builder (with secret redaction)
  policy_engine/ deterministic YAML rule evaluator
  orchestrator/  PR-review + auto-fix flows
  agents/        BaseAgent + 9 specialists
  sandbox/       subprocess / docker runner
  runner/        build/test runner
  tool_proxy/    proxy + simulated tool implementations
  approval/      human approval gate (CLI for MVP)
  audit/         SQLite log
  cli.py         Typer CLI
.claude/
  agents/        9 Claude Code subagents (mirror the Python ones)
  skills/        ai-cicd-run, ai-cicd-triage, ai-cicd-audit
examples/        issue / PR / injection / secret-attempt fixtures
artifacts/       per-pipeline workspaces
logs/            audit.db + structured pipeline results
```

## Using inside Claude Code

This repo ships Claude Code skills and subagents:

- **`ai-cicd-run`** — runs the full pipeline against an event file
- **`ai-cicd-triage`** — runs only the Triage agent
- **`ai-cicd-audit`** — dumps the audit trail for a run
- **9 subagents** under `.claude/agents/` (`triage-agent`, `planner-agent`, …,
  `deployment-agent`) — Claude Code can spawn them individually

Trigger by name in chat (e.g. *"run the cicd on the login bug example"*) or
spawn an individual subagent (*"use the bug-fix-agent on this issue"*).

## Configuration

All knobs in `.env`:

| Var                    | Default                            | Notes                                                |
|------------------------|------------------------------------|------------------------------------------------------|
| `CLAUDE_CLI_API_URL`   | `http://localhost:8765`            | URL of the FastAPI server in `claude-cli-api/`       |
| `CLAUDE_CALL_TIMEOUT`  | `180`                              | Per-call seconds                                     |
| `WORKSPACE_DIR`        | `./artifacts`                      | Per-pipeline workspaces                              |
| `AUDIT_DB_PATH`        | `./logs/audit.db`                  | SQLite                                               |
| `SANDBOX_MODE`         | `subprocess`                       | `subprocess` or `docker`                             |
| `MAX_AGENT_RETRIES`    | `2`                                | Per-agent retry budget                               |
| `AUTO_APPROVE`         | `false`                            | NEVER set true in production                         |

## License & status

MVP / demo. All deploys, PRs, and merges are **simulated** to local files
under `artifacts/<pipeline_id>/`. To turn this into production, replace the
functions in `src/tool_proxy/tools.py` with real `gh` / `kubectl` /
cloud-provider calls — the surrounding gating already works.

---

## v2 — Karpathy-style extensions

The v1 system above is the "make it work" layer. v2 is the "make it
**measurable, learning, and instrumented**" layer, designed around five
Karpathy reflexes:

| Karpathy reflex | v2 module |
|---|---|
| *"Evals are king."* | **Eval Harness** — `evals/cases/*.yaml` + `evals/harness.py` + `ai-cicd eval` |
| *"Tokens are money & latency."* | **Token telemetry** — `src/telemetry/tokens.py` wraps `claude_client`, audit DB stores per-call usage, `ai-cicd cost <pipeline_id>` |
| *"LLM-as-judge & reflection."* | **Critic + Reflector agents** — `src/agents/critic.py`, `src/agents/reflector.py` with prompts + schemas |
| *"Data flywheel — every run produces training data."* | **Memory layer + Archivist** — `memory/<repo>/{conventions,past_patches,pitfalls}` injected into context; `data/runs/*.json` for fine-tune/eval replay |
| *"LLM as OS."* | **Kernel scheduler** — `src/orchestrator/kernel.py` runs DAG nodes in parallel when independent (Security + Code-Review now fan out) |
| *"Lethal trifecta defense."* | **Trifecta auditor** — `src/audit/trifecta.py` + `ai-cicd trifecta-audit` static-checks the approval matrix |

### v2 commands

```bash
ai-cicd eval                        # run all eval cases
ai-cicd eval --agent triage         # only triage cases
ai-cicd cost <pipeline_id>          # per-agent tokens / USD / latency
ai-cicd trifecta-audit              # static check: any agent with all 3 legs?
ai-cicd memory <repo>               # what the system has learned about this repo
ai-cicd reflect <pipeline_id>       # the Reflector's root-cause for a failed/blocked run
```

### Try the flywheel

```bash
# Run a risky PR — pipeline blocks, Reflector explains why, Archivist remembers
ai-cicd run examples/pr_auth_change.json
ai-cicd reflect <pipeline_id>            # → root_cause: failed_security_scan + suggested fix
ai-cicd cost <pipeline_id>               # → per-agent token + USD breakdown
ai-cicd memory demo-org/demo-app          # → past_patches + pitfalls accumulated

# Run the eval harness — measure if your prompt edits improved things
ai-cicd eval                              # → grade every case in evals/cases/
```

### Telemetry shape

Per-agent usage is logged to the audit DB on every call:

```json
{"attempt": 0, "tokens_in": 1804, "tokens_out": 714,
 "cost_usd": 0.016215, "duration_s": 12.83, "estimated": true}
```

Token counts are character-heuristic estimates (`~3.5 chars/token`); they're
flagged `estimated: true` so you don't confuse them with provider-reported
usage. Swap `src/telemetry/tokens.py` with the real provider envelope when
the API exposes it.

### Parallel agent execution

The PR-review flow used to be linear. v2 fans out independent agents:

```
Triage ──► Security Scan  ┐
       └─► Code Review   ─┴──► Validation ──► Critic ──► comment_pr
```

Security and Code Review run concurrently via `kernel.run_dag([...])`. Adding
new parallel branches is one `Task(name=..., fn=..., deps=[...])` away.

### Lethal Trifecta — formalized

Karpathy's framing: an AI agent is dangerous when it has all three of
`(untrusted input, private data, exfiltration)`. `ai-cicd trifecta-audit`
prints a per-agent table and refuses to start if any agent holds all three.
This system intentionally gives **no agent** access to private data, so
nobody hits the lethal trifecta — that's an architecture invariant, not a
runtime hope.

---

## v4 — Production deployment

If Karpathy were shipping this to production at OpenAI, the question wouldn't
be "is it correct" — it would be "**how does it run, restart, get paged on,
debug, and rollback**". v4 is the operational layer.

### Stack

```
                ┌──────────────────────────┐
                │  GitHub / GitLab webhook │
                └─────────────┬────────────┘
                              │ HMAC-verified
                              ▼
                  ┌────────────────────────┐
                  │  pipeline (8000)       │
                  │  /event/<provider>     │
                  │  /run /healthz /readyz │
                  │  /metrics              │
                  │  bounded worker queue  │
                  └─────────────┬──────────┘
                                │ HTTP /chat
                                ▼
                  ┌────────────────────────┐
                  │  gateway (8200)        │      single endpoint
                  │  claude-cli-api        │      wraps both CLIs
                  │  ┌─────────┬────────┐  │
                  │  │ claude  │ gemini │  │      per-call `backend` param
                  │  │  CLI    │  CLI   │  │      lets the Router pick
                  │  └─────────┴────────┘  │
                  └────────────────────────┘
```

Two containers, both with healthchecks. Persisted state (audit DB, artifacts,
memory, dataset) lives in bind-mounted volumes so `make logs` / `ai-cicd audit`
work from the host without `exec`.

### Routing — production stack (v4)

OpenAI provider EXISTS in code (`src/llm/openai.py`) but is intentionally NOT
registered in the Router for this deployment. Production is **Claude CLI +
Gemini CLI** only, both reached through the single `claude-cli-api` gateway.

| Agent | Provider | Why |
|---|---|---|
| triage | gemini | cheap classification |
| planner | claude | deep reasoning |
| bug_fix | claude | code is Claude's strength |
| test_writer | claude | high-quality test generation |
| security_scan | claude | catches CWE-347 etc. in our evals |
| code_review | gemini | second-opinion family — different from author |
| documentation | gemini | cheap doc edits |
| validation | claude | final gate — top model |
| deployment | claude | conservative for prod actions |
| **critic** | **gemini** | **DIFFERENT FAMILY from producers — uncorrelated errors** |
| reflector | gemini | post-mortem from a different family avoids self-defense |

Override at runtime: `AICICD_FORCE_PROVIDER=claude make run`.

### Quick start (docker)

```bash
make up                                        # build + start both services
make ready                                     # confirm both healthchecks green

# Drive a pipeline
make run EVENT=examples/pr_docs_only.json
make run EVENT=examples/pr_auth_change.json    # auth-critical → blocks + reflector fires

# Observe
make logs-pipeline                             # NDJSON structured logs
make audit PIPELINE_ID=pipe-...                # immutable trail
make cost  PIPELINE_ID=pipe-...                # per-agent tokens / USD / latency
make memory REPO=demo-org/demo-app             # learned facts

# Evals + provider comparison
make eval                                      # run eval harness in container
make compare PROVIDERS=claude,gemini           # side-by-side matrix

# Safety gate
make trifecta-audit                            # static check on approval matrix
```

### Webhook ingress

```bash
# GitHub-style payload, HMAC-verified
SECRET="$AICICD_WEBHOOK_SECRET"
BODY='{"action":"opened","pull_request":{...},"repository":{"full_name":"o/r"}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -X POST http://your-host:8000/event/github \
     -H "X-Hub-Signature-256: $SIG" \
     -H "Content-Type: application/json" \
     -d "$BODY"
```

A bad signature → `401`. A full queue → `429 queue full`. Both are correct
back-pressure signals for the upstream load balancer.

### Production observability

- **Logs**: NDJSON when `AICICD_LOG_FORMAT=json` (default in container).
  One log line per event, parseable by `jq` / Loki / Datadog without regex
  hacks. Every line has `pipeline_id` for correlation.
- **Metrics**: `GET /metrics` returns plain JSON
  `{received, processed, failed, queue_depth, total_cost_usd, budget_exceeded}`.
  Plug into Prometheus via a tiny exporter or scrape directly.
- **Cost ceiling**: every pipeline checks against `AICICD_PIPELINE_BUDGET_USD`
  (default $1.00). Exceeded → audit row + `budget_exceeded` log + counter.
- **Healthchecks**: `/healthz` (liveness, always 200 if alive) +
  `/readyz` (503 if gateway unreachable). Wire both to the orchestrator
  (Docker / k8s / nomad).

### Karpathy reflexes baked into v4

| Reflex | Where |
|---|---|
| "Minimal infra; reach for k8s only when proven needed" | docker-compose.yml = 2 services + healthchecks. K8s manifests parked in `deploy/k8s/` for later. |
| "One ops surface; don't make me memorize Docker flags" | `Makefile` is the ONLY interface. `make help` lists everything. |
| "Auth-by-obscurity is auth-by-nothing" | HMAC-verified webhook. `AICICD_WEBHOOK_SECRET` mandatory. |
| "Bounded queues, not infinite ones" | `asyncio.Queue(maxsize=128)` → `429` instead of OOM. |
| "Dev = prod − 1" | `ai-cicd serve` runs the same webhook server locally; `make up` runs the same code in container. |
| "Different-family judge" | Critic = Gemini; producers it grades = mostly Claude. Uncorrelated errors. |
| "Ops > heroics" | [`runbooks/`](runbooks/00_index.md) for provider-down, queue-stuck, lethal-trifecta, cost-spike. Pageable in 2 min. |
| "Cost is a metric, not an afterthought" | Per-pipeline budget ceiling, `make cost` per pipeline, alert hooks documented in runbook 04. |
| **"AI discovers, humans ratchet"** | [Pattern-promotion SOP](runbooks/05_pattern_promotion.md): when AI catches the same thing twice, promote to a deterministic rule + regression test. Closed-loop flywheel. |
| **"Use your own product first"** | **Dogfood workflow — see below.** |

### Dogfood — the pipeline reviews its own PRs

Two workflows ship in `.github/workflows/`:

| Workflow | Trigger | Needs secret | Cost / time |
|---|---|---|---|
| `ci.yml` (deterministic gates) | every push + PR | none | ~30s, free |
| `dogfood-pr-review.yml` (full pipeline review) | PR opened / synchronize | `ANTHROPIC_API_KEY` | ~5–10 min, ~$0.10–0.50 per PR |

**`ci.yml`** — always-on, no API key. Runs:
1. `ai-cicd trifecta-audit` — refuses any PR that introduces a lethal-trifecta agent
2. `ai-cicd providers` — sanity-check the routing YAML parses
3. **Schema integrity** — every `prompts/*.md` has a matching `schemas/*.json` and vice versa
4. **Policy YAML parse** — all files under `policies/*.yaml` are valid YAML

These run in ~30 seconds. Hard gates; PR goes red without arguing.

**`dogfood-pr-review.yml`** — runs the actual pipeline against the PR:
1. Skips silently if `ANTHROPIC_API_KEY` isn't set (forks, draft, external contributors)
2. Installs `claude` CLI + Python deps in the runner
3. Boots the `claude-cli-api` gateway in background
4. `scripts/build_pr_event.py` converts GitHub PR webhook → normalized event JSON (uses `gh pr diff` for the diff)
5. Runs `ai-cicd run /tmp/event.json`
6. `scripts/post_pr_review.py` posts the result as a PR comment — **edits the existing AI-CICD comment in place** (uses hidden `<!-- ai-cicd-review -->` marker) instead of stacking a new one each push
7. Uploads `logs/` + `data/runs/` as workflow artifacts (14-day forensics)
8. Reflects pipeline `final_status` to GitHub check status

Concurrency keyed on PR number with `cancel-in-progress: true` — fast follow-up commit cancels prior run instead of queuing.

**Comment shape:**
```
✅ AI-CICD review — `approved`
Flow `pr_review` · Risk `low` · Cost `$0.0161` · Duration `23.7s`

[validation summary]

### Per-agent
- ✓ triage         (via gemini)
- ✓ security_scan  (via claude)
- ✓ code_review    (via gemini)
- ✓ validation     (via claude)
- ✓ critic         (via gemini)

### Critic scores
- validation: 8/10 — [reasoning grounded in specific output fields]

### Tool calls
- ✓ comment_pr (decision: auto)

Pipeline pipe-... · post-mortem with `make audit PIPELINE_ID=pipe-...`
```

If pipeline blocks (e.g. security flags `critical`), comment also shows the
**Reflector's root-cause + suggested prompt edit**.

**Setup (one-time):**
```bash
git push origin main
gh secret set ANTHROPIC_API_KEY -R your-org/your-repo
# Open a PR — both workflows fire.
```

**Why dogfood matters (the meta point):** every commit to this repo runs through the same pipeline this repo defines. That's the only honest way to know it works:
- If Triage misclassifies → we see it on our own PRs
- If Validation blocks too aggressively → our own PRs slow down
- If costs spike → our own bill goes up
- If a prompt edit regresses → the next PR review tells us

The pipeline can't hide its own bugs from itself.

### Files added in v4

```
deploy/
  Dockerfile.gateway       # node + python image with both CLIs installed
  Dockerfile.pipeline      # python image running webhook + worker
docker-compose.yml         # 2 services, healthchecks, bind-mounted state
Makefile                   # single ops interface (up/down/run/eval/...)

src/server/
  __init__.py
  webhook.py               # FastAPI HMAC-verified ingress + bounded worker pool

runbooks/
  00_index.md
  01_provider_down.md
  02_pipeline_stuck.md
  03_lethal_trifecta.md
  04_cost_spike.md

.github/workflows/
  ci.yml                       # always-on deterministic gates
  dogfood-pr-review.yml        # full pipeline reviews its own PRs
scripts/
  build_pr_event.py            # GitHub PR payload → normalized event JSON
  post_pr_review.py            # pipeline result → PR comment (update-not-stack)

# Modified:
claude-cli-api/main.py     # + per-call `backend` param + /healthz + /readyz
claude-cli-api/planner.py  # + backend_override + skip cached probe when explicit
src/llm/router.py          # claude + gemini providers (openai dropped from registry)
src/llm/claude.py          # sends backend=claude explicitly
src/llm/gemini.py          # NEW
policies/model_routing.yaml # production routing (claude+gemini, critic=different family)
src/cli.py                 # + ai-cicd serve subcommand
pyproject.toml             # + fastapi, uvicorn deps; + src.server, src.llm packages
```

---

## v3 — Karpathy at OpenAI

If Karpathy were building this *at* OpenAI, the question wouldn't be "Claude
or OpenAI" — it would be "**which model for which agent**, and prove it with
data." v3 makes the system provider-agnostic and adds the tooling to answer
that question.

### What's new

| Karpathy reflex | v3 piece |
|---|---|
| *"Provider isn't a religion."* | `src/llm/{base,claude,openai,router}.py` — agents only talk to a `Router`; provider is a config decision |
| *"Right-size models per task."* | `policies/model_routing.yaml` — Triage on `gpt-5-nano`, Validation on `gpt-5`, Security on `o3-mini`, Bug Fix on Claude, Critic on a *different family* than producers |
| *"Structured Outputs eliminate the retry loop."* | `openai-api/` passes `response_format: json_schema`; the parse-and-retry loop in BaseAgent now skips on success |
| *"Real tokens, not heuristics."* | `openai-api/` returns the real `usage` object; `OpenAIProvider` uses real prices; telemetry only marks `estimated: true` for Claude path |
| *"Eval-driven provider selection."* | `ai-cicd compare --providers claude,openai` runs the eval suite on each and prints a side-by-side matrix |
| *"Independent judge."* | Critic agent is routed to a *different family* than the producer it grades — uncorrelated errors |

### v3 commands

```bash
ai-cicd providers                                 # show per-agent routing table
ai-cicd compare --providers claude,openai         # side-by-side eval matrix
ai-cicd compare -p claude,openai --agent triage   # only triage cases
AICICD_FORCE_PROVIDER=openai ai-cicd run ...      # bulk override for one run
AICICD_FORCE_MODEL=gpt-5-mini ai-cicd eval        # try a different model size
```

### Run the OpenAI backend

```bash
# Terminal 1 — Claude CLI server (already running for v1/v2)
cd claude-cli-api && PLANNER_BACKEND=claude PORT=8200 python main.py

# Terminal 2 — OpenAI server (NEW)
cd openai-api
cp .env.example .env                                    # add OPENAI_API_KEY
PORT=8300 python main.py                                 # live mode
# OR for keyless dev:
OPENAI_MOCK=true PORT=8300 python main.py                # deterministic mock

# Terminal 3 — drive the pipeline
ai-cicd health                                           # both providers
ai-cicd providers                                        # routing table
ai-cicd run examples/pr_docs_only.json                   # multi-provider run
ai-cicd compare -p claude,openai                         # which is better per case?
```

### Routing table (default)

| Agent | Provider | Model | Why this choice |
|---|---|---|---|
| triage | openai | `gpt-5-nano` | classification; cheapest tier suffices |
| planner | openai | `gpt-5` | planning needs strong reasoning |
| bug_fix | claude | (default) | code patching is Claude's strength in our evals |
| test_writer | claude | (default) | same — Claude tends to write higher-quality tests |
| security_scan | openai | `o3-mini` | reasoning model — security needs careful chain-of-thought |
| code_review | openai | `gpt-5` | top reasoning |
| documentation | openai | `gpt-5-nano` | doc rewrites are cheap |
| validation | openai | `gpt-5` | final gate — strongest model |
| deployment | openai | `gpt-5-nano` | follow a checklist, no reasoning |
| critic | claude | (default) | **different family** from validation/code_review producers |
| reflector | openai | `gpt-5` | post-mortem needs deep analysis |

You can change any row without touching agent code. That's the point.

### OpenAI Structured Outputs path

When an agent runs against the OpenAI provider, `BaseAgent` ships its JSON
schema via `response_format: {type: json_schema, ...}`. The model is
guaranteed to emit a schema-conforming reply, so the JSON-extraction +
schema-validate retry loop only fires on the Claude path. Concretely:

```
Claude path:  raw text → fenced-JSON regex → jsonschema.validate → retry on fail
OpenAI path:  schema-mode reply → jsonschema.validate (defensive) → done
```

### `ai-cicd compare` — what it actually shows

```
                        ┃ claude    ┃ openai           ┃
 triage__login_bug      ┃ PASS 7.8s ┃ PASS 1.4s        ┃   ← openai wins on speed
 triage__prompt_injection┃ PASS 6.9s┃ FAIL severity... ┃   ← claude wins on quality
 security__jwt_none      ┃ PASS 18s ┃ PASS 12s         ┃
                        ┃ 3/3       ┃ 2/3              ┃
```

Decision: route `triage` to whoever wins; route `security_scan` to whoever
wins; etc. **Data, not vibes.**

### Files added in v3

```
openai-api/                          # FastAPI server, /chat contract identical to claude-cli-api
  main.py
  openai_client.py                   # real usage, structured outputs, mock mode
  pyproject.toml  setup.sh  .env.example

src/llm/
  base.py     LLMProvider + CallResult interface
  claude.py   ClaudeProvider (wraps claude-cli-api)
  openai.py   OpenAIProvider (wraps openai-api, real prices)
  router.py   Per-agent routing driven by yaml + env overrides

policies/model_routing.yaml          # which model for which agent

# CLI:  ai-cicd providers   ai-cicd compare
```

---

### Files added in v2

```
prompts/critic.md   prompts/reflector.md
schemas/critic.json  schemas/reflector.json
src/telemetry/tokens.py
src/agents/critic.py  src/agents/reflector.py
src/memory/store.py  src/memory/archivist.py
src/orchestrator/kernel.py
src/audit/trifecta.py
src/audit/dataset.py
evals/harness.py    evals/cases/*.yaml
```
