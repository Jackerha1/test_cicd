# AI-Powered CI/CD

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
