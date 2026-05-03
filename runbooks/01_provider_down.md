# 01 — Provider down (claude / gemini CLI)

## Symptom

- `make ready` returns `503` from `gateway:` or `pipeline:`.
- Pipeline runs fail with `provider_call_failed: ...`.
- `/metrics` shows `failed` rising while `processed` stays flat.

## First check

```bash
make ready
docker compose logs --tail=50 gateway | grep -E '(claude|gemini)_cli'
```

You're looking for one of:
- `claude_cli: available=False` — claude CLI unauthenticated or removed
- `gemini_cli: available=False` — gemini CLI broken (often config error)
- gateway healthcheck timing out — gateway process crashed

## Mitigate (restore service in <2 min)

**One CLI down, the other up:**
```bash
# Force the up one for ALL agents until the broken one is fixed.
docker compose exec pipeline sh -c \
  "AICICD_FORCE_PROVIDER=claude python -m src.server.webhook" &
# (or =gemini)
```

The pipeline keeps running; per-agent routing is overridden globally.

**Gateway crashed:**
```bash
make restart        # docker compose restart
make ready          # confirm green
```

## Root-cause

- **Auth expired**: `docker compose exec gateway claude --version` /
  `gemini --version`. Re-login: `claude login` / `gemini auth login`. The
  `~/.claude` and `~/.gemini` dirs are mounted from host (see
  `docker-compose.yml`), so re-login on host then `make restart`.

- **Gemini settings.json schema**: gemini CLI rejects unrecognized keys in
  `~/.gemini/settings.json` (e.g. stray `name` or `transport` under
  `mcpServers.*`). Validate:
  ```bash
  gemini --version
  ```
  Edit `~/.gemini/settings.json`, remove offending keys, retry.

- **Network**: gateway can reach Anthropic / Google? Try
  `docker compose exec gateway curl -fsS https://api.anthropic.com`.

## Prevention

- The Router is provider-agnostic: every agent has a fallback by setting a
  per-agent `default` block in `policies/model_routing.yaml`.
- Add an alert on `failed / processed > 0.05` over 10 min.
- Quarterly: rotate auth tokens proactively; don't wait for them to expire.
