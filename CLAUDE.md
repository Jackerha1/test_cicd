# CLAUDE.md

> **For AI assistants (Claude Code / GPT / Gemini / etc.): read this first.**
> This file is auto-loaded into every session so you understand the repo's
> identity, invariants, and operating rules without being asked.

## What this repo is

`Jackerha1/test_cicd` hosts **two coupled artifacts**:

1. **The AI-CICD pipeline source** — a multi-agent CI/CD reviewer that runs
   on the maintainer's host, receives GitHub webhook events, fetches the PR
   diff, runs 11 specialist agents (triage / planner / bug_fix / test_writer /
   security_scan / code_review / documentation / validation / deployment +
   critic + reflector), and posts an idempotent review comment on the PR.
2. **`crud-demo/`** — a small Flask + React app whose only purpose is to
   give the pipeline a non-trivial codebase to review. It is the *target*,
   not the pipeline. Don't confuse the two.

Production deployment topology:

```
GitHub repo  →  webhook (HMAC)  →  cloudflared tunnel  →  pipeline (:8000)
                                                            ↓ HTTP /chat
                                                          gateway (:8200)
                                                            ↓
                                              claude CLI + gemini CLI on host
```

## Branch policy (HARD)

- **`main`** — protected (1 reviewer + linear history + status checks +
  no force-push + no delete + conversation resolution required). Holds
  the pipeline source. NEVER opens or accepts PRs from `develop`.
- **`develop`** — active branch. PRs land here. AI-CICD pipeline reviews
  PRs targeting `develop`. Includes the latest pipeline source AND
  `crud-demo/`.
- Feature branches: cut from `develop`, PR back to `develop`. No exceptions.

When the user says "open a PR", the base is `develop` unless they explicitly
say `main`. Never auto-target `main`.

## Architecture (6 layers)

1. **Trigger** — webhook receiver + queue, HMAC-verified, bounded
   (`src/server/webhook.py`)
2. **Auth & Permission** — checks event author against `policies/allowed_authors.yaml`
3. **Context Builder** — fetches PR diff via REST, redacts secrets, assembles
   per-agent context
4. **Policy Engine** — DETERMINISTIC. YAML-driven. Fires before any agent.
   Path globs + diff regex matching (`src/policy_engine/engine.py`)
5. **Orchestrator + Agents + Tool Proxy** — kernel scheduler runs DAG; agents
   produce JSON; Tool Proxy is the single chokepoint for external actions
6. **Audit / Memory / Dataset** — append-only SQLite, per-repo memory layer,
   per-run dataset for offline analysis

## What you SHOULD do without asking

- Read code files to answer questions about the system
- Run `make ready`, `make audit PIPELINE_ID=...`, `make cost PIPELINE_ID=...`
- Run `ai-cicd eval --target policy_engine` and `ai-cicd trifecta-audit`
- Inspect `data/runs/*.json`, `logs/audit.db`, `memory/<repo>/`
- Run `pytest` in `crud-demo/backend/` or `vitest` in `crud-demo/frontend/`
- Use `./scripts/pilot.sh status` to see live state

## What you MUST ask before doing

- Modifying `policies/*.yaml` — these are SECURITY config; show diff + ask
- Modifying `prompts/*.md` or `schemas/*.json` — affects every future review
- Pushing any branch (pre-push hook needs interactive `y/N`; user has to do it)
- Running `gh api -X PATCH` / `gh api -X DELETE` on the live repo
- Configuring or rotating webhook secret
- Force-pushing or rewriting history on any branch

## What you MUST NEVER do

- `git push --force` to `main` (protected)
- Bypass the pre-push hook with `--no-verify`
- Commit `.env` (it's gitignored; if you see it staged, untrack with `git rm --cached .env`)
- Add `'none'` to JWT algorithms (CWE-347; `jwt_none_bypass` rule will block at policy)
- Modify `crud-demo/backend/app/auth.py` to weaken bcrypt / JWT / generic-error pattern
- Set `AUTO_APPROVE=true` in any non-throwaway env
- Promote a deterministic policy rule WITHOUT also adding a regression eval case
  (see `runbooks/05_pattern_promotion.md` — non-negotiable)

## Files you SHOULD NOT casually edit

| Path | Why |
|---|---|
| `src/agents/*.py` | tested orchestration; changes need eval coverage |
| `src/orchestrator/*.py` | core flow; changes need integration tests |
| `src/policy_engine/engine.py` | deterministic invariant; changes need eval |
| `src/llm/*.py` | provider abstraction; affects every agent call |
| `prompts/*.md` | system prompts; changes affect every future review |
| `schemas/*.json` | output contracts; backwards compat needed |
| `runbooks/*.md` | operational SOPs; only edit with reviewed PR |

## Files you SHOULD edit when adapting to a new use case

| Path | When |
|---|---|
| `policies/risk_rules.yaml` | each new repo has different auth/payment paths |
| `policies/allowed_authors.yaml` | trusted committers per repo |
| `policies/model_routing.yaml` | tune provider/model per agent based on evals |
| `examples/*.json` | add fixtures for new event scenarios |
| `evals/cases/*.yaml` | add regression tests for new policy rules (REQUIRED on rule promotion) |

## Operating commands

```bash
# Full lifecycle
./scripts/pilot.sh up          # start everything (gateway + pipeline + tunnel + webhook)
./scripts/pilot.sh down        # stop everything
./scripts/pilot.sh status      # current state
./scripts/pilot.sh restart     # down + up

# Individual services (Makefile)
make gateway                   # host claude+gemini gateway on :8200
make up                        # pipeline container on :8000
make ready                     # confirm both healthchecks
make logs                      # NDJSON pipeline logs

# Forensics
make audit  PIPELINE_ID=pipe-...   # immutable trail
make cost   PIPELINE_ID=pipe-...   # tokens / USD / latency per agent
make memory REPO=owner/name        # learned facts per repo

# Quality gates (always-free, deterministic)
ai-cicd eval --target policy_engine    # regression tests for promoted rules
ai-cicd trifecta-audit                  # static check on approval matrix
```

## When the user describes a problem, check these first

| Symptom | First check |
|---|---|
| "Pipeline didn't review my PR" | `./scripts/pilot.sh status` — is everything up? |
| "Pipeline blocked something it shouldn't" | `make audit PIPELINE_ID=...` — find the rule that fired |
| "Cost spike" | `make cost PIPELINE_ID=...` + `runbooks/04_cost_spike.md` |
| "Comment posted twice on PR" | search for missing `<!-- ai-cicd-review -->` marker handling |
| "AI keeps catching the same pattern" | `runbooks/05_pattern_promotion.md` — promote it |

## Where to look for "how do I…"

| Question | Doc |
|---|---|
| How do I deploy this to a new repo? | `DEPLOY_TO_NEW_PROJECT.md` (human) or `SETUP.md` (AI-readable) |
| How do I wire it to *this* repo specifically? | `PILOT_SETUP.md` |
| What's the architecture? | `ARCHITECTURE.md` |
| How do I handle X failure? | `runbooks/01-04_*.md` |
| What's the ops procedure for promoting a rule? | `runbooks/05_pattern_promotion.md` |

## Pre-push hook

The user's git config has a "MẮT THẦN AUTO-CHECK GIT ACCOUNT" pre-push hook
that requires interactive `y/N` confirmation. **You cannot bypass it from
non-interactive shells**. When code is ready to push, tell the user the
exact command and let them run it manually. Do NOT try `--no-verify`.

## Provider routing (current default)

`policies/model_routing.yaml` routes most agents to **gemini** (cheap,
fast classification + review) with **claude** for the **critic**
(different family — uncorrelated errors). Override with
`AICICD_FORCE_PROVIDER=claude` env when needed for incidents.

## Karpathy invariants (the design's North Star)

1. **AI agents are non-deterministic; pipeline outcomes must be deterministic.**
   Solution: deterministic gates first, AI as additional signal.
2. **Containment > trust.** Agents have least-privilege capability ceilings
   in `policies/approval_matrix.yaml`.
3. **Different-family judge.** Critic is always a different LLM family than
   the producer it grades.
4. **Every promoted rule earns a regression test.** No exceptions.
5. **Use your own product first.** This repo's PRs are reviewed by its own
   pipeline.

If a change you're about to make would break one of these invariants, stop
and ask the user.
