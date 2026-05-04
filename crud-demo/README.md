# crud-demo — Tasks API + UI

A small, intentionally-realistic CRUD app whose only purpose is to give the
**AI-CICD pipeline** (in `../`) a non-trivial codebase to review on every PR.

> **Read this if you are a contributor**: changes to `crud-demo/` open PRs
> against the `develop` branch. Those PRs are reviewed by the multi-agent
> pipeline running on the maintainer's host. Don't expect a human reviewer
> first — the pipeline comments first, you respond, then a human merges.

## Stack

| Layer | Tech | Why |
|---|---|---|
| Backend | Flask + Flask-SQLAlchemy + PyJWT + bcrypt | Familiar surface for the security/code-review agents |
| Database | SQLite (file: `app.db`) | Zero-config; this is a CI/CD-pipeline test, not a scale demo |
| Frontend | React 18 + Vite + plain CSS | Minimal — we want the pipeline reviewing real code, not framework boilerplate |
| Tests | pytest (backend) + vitest (frontend) | Real assertions, no `assert True` |

## Domain

Two entities. Auth required for everything except `/register` and `/login`.

### `User`
- `id` (int, PK)
- `username` (unique, 3–32 chars)
- `password_hash` (bcrypt)
- `created_at`

### `Task`
- `id` (int, PK)
- `user_id` (FK → User)
- `title` (1–120 chars)
- `description` (≤ 2000 chars, nullable)
- `status` (`todo` | `in_progress` | `done`)
- `due_date` (date, nullable)
- `created_at`, `updated_at`

## Endpoints

```
POST   /api/auth/register     {username, password}              → 201 {token}
POST   /api/auth/login        {username, password}              → 200 {token}
GET    /api/tasks                                                → 200 [Task]
POST   /api/tasks             {title, description?, due_date?}  → 201 Task
GET    /api/tasks/<id>                                           → 200 Task
PUT    /api/tasks/<id>        {…}                                → 200 Task
DELETE /api/tasks/<id>                                           → 204
```

All `/api/tasks*` routes require `Authorization: Bearer <jwt>`.

## Dev

```bash
cd crud-demo
docker compose up                   # starts backend:5000 + frontend:5173 + serves SQLite

# OR run pieces directly:
( cd backend && python -m venv .venv && source .venv/bin/activate && \
  pip install -e . && flask --app app:create_app run --debug --port 5000 )

( cd frontend && npm install && npm run dev )
```

## Test

```bash
cd crud-demo/backend  && pytest -q
cd crud-demo/frontend && npm test -- --run
```

## How AI-CICD reviews this code

When you open a PR against `develop` (the repo's protected base for crud-demo work),
the pipeline running on the maintainer's host runs all 11 agents. Within 1–3 min,
a single comment appears on the PR with:

- **Triage** — kind + severity + scope
- **Security Scan** — OWASP / secrets / supply-chain findings (if any)
- **Code Review** — logic, scope creep, convention drift
- **Validation** — final verdict: approve | request_changes | block
- **Critic** (different family from above) — independent grade of validation
- **Reflector** (only on block/fail) — root cause + suggested policy/prompt fix

If you disagree with the agent comment, push a follow-up commit explaining
why; the pipeline re-runs and updates the same comment in place (no spam).

The pipeline does NOT auto-merge. Humans merge.
