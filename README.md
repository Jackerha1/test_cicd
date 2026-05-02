# AI-Powered CI/CD

> **v2 — Karpathy lens applied**: eval harness, token/cost telemetry, Critic
> + Reflector agents, per-repo memory, LLM-OS parallel kernel, lethal-trifecta
> auditor, data flywheel. See [the v2 section below](#v2--karpathy-style-extensions)
> or [ARCHITECTURE.md](ARCHITECTURE.md).


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
