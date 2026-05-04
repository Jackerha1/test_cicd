#!/usr/bin/env bash
# pilot.sh — single ops script for the AI-CICD pilot on this repo.
#
# Subcommands:
#   up        start gateway (host) + pipeline (docker) + cloudflared tunnel,
#             then create or update the GitHub webhook with the new URL.
#   down      stop everything cleanly (pipeline container, host gateway,
#             tunnel). Idempotent.
#   status    show current state of every component.
#   restart   down + up.
#   help      this message.
#
# Karpathy: one ops surface, predictable verbs. Don't add a subcommand
# without also documenting it in CLAUDE.md / DEPLOY_TO_NEW_PROJECT.md.

set -euo pipefail

# --- config ---------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE=".env"
GATEWAY_PORT=8200
PIPELINE_PORT=8000

# Track tunnel + webhook ids in .env so subsequent runs can update instead of duplicate.
TUNNEL_LOG="/tmp/aicicd-cloudflared.log"
TUNNEL_PID="/tmp/aicicd-cloudflared.pid"

# Fallback target repo for this pilot — override by exporting AICICD_TARGET_REPO.
TARGET_REPO="${AICICD_TARGET_REPO:-Jackerha1/test_cicd}"

# --- pretty printing -----------------------------------------------------

C_GREEN='\033[32m'; C_RED='\033[31m'; C_YEL='\033[33m'; C_DIM='\033[2m'; C_RESET='\033[0m'
ok()    { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_YEL}⚠${C_RESET} %s\n" "$*"; }
fail()  { printf "${C_RED}✗${C_RESET} %s\n" "$*"; }
info()  { printf "${C_DIM}» %s${C_RESET}\n" "$*"; }
hr()    { printf "${C_DIM}%s${C_RESET}\n" "─────────────────────────────────────────────────────"; }

# --- preflight -----------------------------------------------------------

ensure_tools() {
  local missing=()
  for t in docker make curl gh openssl cloudflared claude gemini; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    fail "missing tools: ${missing[*]}"
    info "see DEPLOY_TO_NEW_PROJECT.md §0 for install commands"
    exit 2
  fi
}

ensure_secrets() {
  if [[ ! -f "$ENV_FILE" ]]; then
    warn ".env missing — creating from .env.example"
    cp .env.example "$ENV_FILE"
  fi

  if ! grep -q "^AICICD_WEBHOOK_SECRET=." "$ENV_FILE"; then
    info "generating AICICD_WEBHOOK_SECRET"
    local s; s=$(openssl rand -hex 32)
    if grep -q "^AICICD_WEBHOOK_SECRET=" "$ENV_FILE"; then
      # macOS sed needs '' arg
      sed -i.bak "s|^AICICD_WEBHOOK_SECRET=.*|AICICD_WEBHOOK_SECRET=$s|" "$ENV_FILE"
      rm -f "${ENV_FILE}.bak"
    else
      printf "AICICD_WEBHOOK_SECRET=%s\n" "$s" >> "$ENV_FILE"
    fi
  fi

  if ! grep -q "^GITHUB_TOKEN=." "$ENV_FILE"; then
    info "populating GITHUB_TOKEN from gh auth token"
    local t; t=$(gh auth token 2>/dev/null) || { fail "gh auth token failed — run 'gh auth login'"; exit 2; }
    if grep -q "^GITHUB_TOKEN=" "$ENV_FILE"; then
      sed -i.bak "s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$t|" "$ENV_FILE"
      rm -f "${ENV_FILE}.bak"
    else
      printf "GITHUB_TOKEN=%s\n" "$t" >> "$ENV_FILE"
    fi
  fi
}

# --- gateway (host-side) -------------------------------------------------

gateway_up() {
  if curl -fsS "http://localhost:$GATEWAY_PORT/readyz" >/dev/null 2>&1; then
    ok "gateway already up on :$GATEWAY_PORT"
    return
  fi
  info "starting host gateway (claude + gemini behind /chat)"
  make gateway >/dev/null 2>&1
  for _ in $(seq 1 30); do
    sleep 1
    curl -fsS "http://localhost:$GATEWAY_PORT/readyz" >/dev/null 2>&1 && { ok "gateway ready"; return; }
  done
  fail "gateway didn't become ready within 30s — check logs at /tmp/ai-cicd-gateway.log"
  exit 2
}

gateway_down() {
  if curl -fsS "http://localhost:$GATEWAY_PORT/readyz" >/dev/null 2>&1; then
    info "stopping host gateway"
    make gateway-stop >/dev/null 2>&1 || true
    # Some uvicorn child workers escape the pidfile; kill them too.
    if lsof -nP -iTCP:$GATEWAY_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
      lsof -nP -iTCP:$GATEWAY_PORT -sTCP:LISTEN -t | xargs -r kill 2>/dev/null || true
      sleep 1
    fi
  fi
  if lsof -nP -iTCP:$GATEWAY_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn ":$GATEWAY_PORT still occupied"
  else
    ok "gateway stopped"
  fi
}

# --- pipeline (container) ------------------------------------------------

pipeline_up() {
  if curl -fsS "http://localhost:$PIPELINE_PORT/healthz" >/dev/null 2>&1; then
    ok "pipeline already up on :$PIPELINE_PORT"
    return
  fi
  info "building + starting pipeline container"
  make build  >/dev/null
  docker compose up -d pipeline >/dev/null
  for _ in $(seq 1 30); do
    sleep 1
    curl -fsS "http://localhost:$PIPELINE_PORT/readyz" >/dev/null 2>&1 && { ok "pipeline ready"; return; }
  done
  fail "pipeline didn't become ready within 30s — check 'make logs'"
  exit 2
}

pipeline_down() {
  if docker compose ps -q pipeline >/dev/null 2>&1 \
     && [[ -n "$(docker compose ps -q pipeline 2>/dev/null)" ]]; then
    info "stopping pipeline container"
    docker compose down >/dev/null 2>&1
    ok "pipeline stopped"
  else
    info "pipeline already stopped"
  fi
}

# --- cloudflared tunnel --------------------------------------------------

tunnel_up() {
  if [[ -f "$TUNNEL_PID" ]] && kill -0 "$(cat "$TUNNEL_PID")" 2>/dev/null; then
    if [[ -f "$TUNNEL_LOG" ]] && grep -q 'trycloudflare\.com' "$TUNNEL_LOG"; then
      local existing; existing=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1)
      ok "tunnel already up — $existing"
      printf '%s\n' "$existing" > /tmp/aicicd-tunnel-url
      return
    fi
  fi

  info "starting cloudflared tunnel (http2 mode)"
  : > "$TUNNEL_LOG"
  cloudflared tunnel --url "http://localhost:$PIPELINE_PORT" --protocol http2 \
    > "$TUNNEL_LOG" 2>&1 &
  echo $! > "$TUNNEL_PID"

  for _ in $(seq 1 30); do
    sleep 1
    if grep -q 'trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null; then
      local url; url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1)
      printf '%s\n' "$url" > /tmp/aicicd-tunnel-url
      ok "tunnel ready — $url"
      return
    fi
  done
  fail "tunnel didn't come up within 30s — check $TUNNEL_LOG"
  exit 2
}

tunnel_down() {
  if [[ -f "$TUNNEL_PID" ]] && kill -0 "$(cat "$TUNNEL_PID")" 2>/dev/null; then
    info "stopping cloudflared tunnel"
    kill "$(cat "$TUNNEL_PID")" 2>/dev/null || true
    rm -f "$TUNNEL_PID"
    ok "tunnel stopped"
  fi
  # belt-and-suspenders: kill any orphan cloudflared processes
  pgrep -f 'cloudflared tunnel' | xargs -r kill 2>/dev/null || true
  rm -f /tmp/aicicd-tunnel-url
}

# --- GitHub webhook ------------------------------------------------------

webhook_sync() {
  local url; url=$(cat /tmp/aicicd-tunnel-url 2>/dev/null) || { fail "no tunnel URL"; return 1; }
  local secret; secret=$(grep "^AICICD_WEBHOOK_SECRET=" "$ENV_FILE" | cut -d= -f2)

  # If we already have a hook id remembered, PATCH it. Else look one up by
  # whether any existing hook URL matches our path; otherwise POST a new one.
  local hook_id
  hook_id=$(grep "^AICICD_WEBHOOK_ID=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || true)

  if [[ -z "$hook_id" ]]; then
    # Look for an existing webhook ending in /event/github
    hook_id=$(gh api "repos/$TARGET_REPO/hooks" \
                --jq '.[] | select(.config.url | endswith("/event/github")) | .id' 2>/dev/null \
              | head -1 || true)
  fi

  if [[ -n "$hook_id" ]]; then
    info "updating webhook $hook_id with new tunnel URL"
    gh api -X PATCH "repos/$TARGET_REPO/hooks/$hook_id" \
      -F "config[url]=$url/event/github" \
      -F "config[secret]=$secret" \
      -F "config[content_type]=json" >/dev/null
    ok "webhook updated → $url/event/github"
  else
    info "creating webhook on $TARGET_REPO"
    hook_id=$(gh api -X POST "repos/$TARGET_REPO/hooks" \
                -f name=web -F active=true \
                -F "config[url]=$url/event/github" \
                -F "config[content_type]=json" \
                -F "config[secret]=$secret" \
                -F "config[insecure_ssl]=0" \
                -F 'events[]=pull_request' \
                -F 'events[]=issues' \
                -F 'events[]=issue_comment' \
                --jq '.id')
    ok "webhook created — id $hook_id → $url/event/github"
    if grep -q '^AICICD_WEBHOOK_ID=' "$ENV_FILE"; then
      sed -i.bak "s|^AICICD_WEBHOOK_ID=.*|AICICD_WEBHOOK_ID=$hook_id|" "$ENV_FILE"
      rm -f "${ENV_FILE}.bak"
    else
      printf "AICICD_WEBHOOK_ID=%s\n" "$hook_id" >> "$ENV_FILE"
    fi
  fi
}

webhook_smoke() {
  local url; url=$(cat /tmp/aicicd-tunnel-url 2>/dev/null) || return 1
  local secret; secret=$(grep "^AICICD_WEBHOOK_SECRET=" "$ENV_FILE" | cut -d= -f2)
  local body='{"action":"opened","pull_request":{"number":0,"title":"smoke","body":"","user":{"login":"pilot"},"head":{"ref":"x"},"base":{"ref":"develop"}},"repository":{"full_name":"'"$TARGET_REPO"'"}}'
  local sig; sig="sha256=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$secret" | awk '{print $2}')"
  if curl -sf -X POST "$url/event/github" \
       -H "X-Hub-Signature-256: $sig" \
       -H "X-GitHub-Event: pull_request" \
       -H "Content-Type: application/json" \
       -d "$body" >/dev/null; then
    ok "webhook end-to-end smoke passed"
  else
    fail "webhook smoke failed — pipeline reachable but rejected the signature"
    return 1
  fi
}

# --- subcommands ---------------------------------------------------------

cmd_up() {
  hr
  echo "AI-CICD pilot — UP   (target repo: $TARGET_REPO)"
  hr
  ensure_tools
  ensure_secrets
  gateway_up
  pipeline_up
  tunnel_up
  webhook_sync
  webhook_smoke || warn "smoke failed; continuing"
  hr
  ok "pilot is live"
  echo
  info "GitHub webhook will deliver pull_request / issues / issue_comment events"
  info "to the tunnel URL above. Open a PR on $TARGET_REPO targeting 'develop'."
  info "Watch:   make logs"
  info "Audit:   make audit  PIPELINE_ID=pipe-..."
  info "Cost:    make cost   PIPELINE_ID=pipe-..."
  info "Stop:    ./scripts/pilot.sh down"
}

cmd_down() {
  hr
  echo "AI-CICD pilot — DOWN"
  hr
  tunnel_down
  pipeline_down
  gateway_down
  hr
  ok "pilot is offline"
}

cmd_status() {
  hr
  echo "AI-CICD pilot — STATUS"
  hr
  # Gateway
  if curl -fsS "http://localhost:$GATEWAY_PORT/readyz" >/dev/null 2>&1; then
    local body; body=$(curl -s "http://localhost:$GATEWAY_PORT/readyz")
    ok "gateway        :$GATEWAY_PORT  $body"
  else
    fail "gateway        :$GATEWAY_PORT  not running"
  fi
  # Pipeline
  if curl -fsS "http://localhost:$PIPELINE_PORT/readyz" >/dev/null 2>&1; then
    local body; body=$(curl -s "http://localhost:$PIPELINE_PORT/readyz")
    ok "pipeline       :$PIPELINE_PORT  $body"
    local m; m=$(curl -s "http://localhost:$PIPELINE_PORT/metrics")
    info "metrics        $m"
  else
    fail "pipeline       :$PIPELINE_PORT  not running"
  fi
  # Tunnel
  if [[ -f "$TUNNEL_PID" ]] && kill -0 "$(cat "$TUNNEL_PID")" 2>/dev/null; then
    local url; url=$(cat /tmp/aicicd-tunnel-url 2>/dev/null || echo unknown)
    ok "tunnel         pid=$(cat "$TUNNEL_PID")  url=$url"
  else
    fail "tunnel         not running"
  fi
  # Webhook
  if [[ -f "$ENV_FILE" ]]; then
    local hid; hid=$(grep "^AICICD_WEBHOOK_ID=" "$ENV_FILE" | cut -d= -f2 || true)
    if [[ -n "$hid" ]]; then
      local last; last=$(gh api "repos/$TARGET_REPO/hooks/$hid" \
                          --jq '{url: .config.url, last_response: .last_response.status}' 2>/dev/null \
                        || echo "(failed to fetch)")
      ok "webhook        id=$hid  $last"
    else
      info "webhook        not configured"
    fi
  fi
  # Container
  local cs; cs=$(docker compose ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null | tail -n +2 | head -3)
  [[ -n "$cs" ]] && info "containers     $cs"
  hr
}

cmd_restart() {
  cmd_down
  echo
  cmd_up
}

cmd_help() {
  cat <<EOF
pilot.sh — AI-CICD pilot lifecycle for $TARGET_REPO

Usage:
  ./scripts/pilot.sh <subcommand>

Subcommands:
  up         Start gateway, pipeline, tunnel, sync GitHub webhook, smoke-test.
             Idempotent — safe to run when already up.
  down       Stop tunnel, pipeline, gateway. Idempotent.
  status     Print current state of every component + last webhook delivery.
  restart    down + up.
  help       This message.

Env overrides:
  AICICD_TARGET_REPO   Override the GitHub repo (default: Jackerha1/test_cicd)
EOF
}

# --- entry --------------------------------------------------------------

case "${1:-help}" in
  up)       cmd_up ;;
  down)     cmd_down ;;
  status)   cmd_status ;;
  restart)  cmd_restart ;;
  help|-h|--help) cmd_help ;;
  *)        fail "unknown subcommand: $1"; cmd_help; exit 2 ;;
esac
