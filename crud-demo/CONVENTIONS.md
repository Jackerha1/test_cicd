# crud-demo — code conventions

> The AI-CICD Code Review Agent reads this file as part of context. Anything
> here is treated as repo-specific style guidance.

## Backend (Python / Flask)

1. **Routes only orchestrate.** No SQL or password hashing in routes; that
   lives in `app/services/` modules. Routes call services, return JSON.
2. **No `import *`**. Explicit imports.
3. **Type hints on public function signatures.** Internal helpers may skip.
4. **No print/debug logging** — use `app.logger.info(...)`.
5. **DB access through SQLAlchemy session**, not raw `sqlite3`. The session
   lives in `app/db.py`.
6. **All input validated** with marshmallow / pydantic (we use marshmallow).
   Don't trust request payloads.
7. **Error responses** are JSON `{"error": "<code>", "message": "<human>"}`,
   never plaintext, never stack traces.
8. **Tests live next to features**: `app/routes/auth.py` ↔ `tests/test_auth_routes.py`.
9. **No `assert True` / empty mocks.** Test Writer Agent's `post_validate`
   refuses these — and so do we.

## Frontend (React)

1. **Functional components + hooks only.** No class components.
2. **Fetch goes through `src/lib/api.js`** — never inline `fetch()` in components.
3. **JWT in `localStorage`** under key `aicicd:token`. Never commit a token.
4. **Component file = component name + `.jsx`** (e.g. `TaskList.jsx`).
5. **CSS** — vanilla CSS in `src/styles/*.css`, no Tailwind / styled-components
   for this demo.
6. **Tests** colocated as `<Component>.test.jsx`. Vitest + RTL.

## Security defaults (do not weaken)

These are enforced by the AI-CICD security scan. If you change one, expect
the pipeline to block until a human approves.

- Passwords: **bcrypt**, cost ≥ 12. No SHA / MD5 / plaintext.
- JWT: **HS256** with rotating secret from env. **Never** add `none`
  algorithm. (See `policies/risk_rules.yaml:jwt_none_bypass`.)
- SQL: only via SQLAlchemy ORM — no string-formatted queries.
- CORS: only the dev frontend origin.
- File uploads: not part of this demo. Don't add without a separate PR.

## Commit style

```
<type>: <imperative subject in lowercase>

<body explaining WHY, wrapped at ~72 chars>
```

`<type>` ∈ `feat`, `fix`, `chore`, `test`, `docs`, `refactor`. The Triage
agent uses these to set kind and severity.
