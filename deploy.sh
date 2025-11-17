#!/usr/bin/env bash
# deploy.sh — simple prod deploy helper for Vinyl Record Tracker
#
# Usage:
#   ./deploy.sh                 # build & restart app + frontend
#   ./deploy.sh app             # build & restart only app
#   ./deploy.sh frontend        # build & restart only frontend
#   ./deploy.sh caddy           # restart only caddy (no build)
#   ./deploy.sh up              # start all (no build)
#   ./deploy.sh down            # stop all
#   ./deploy.sh logs [svc]      # tail logs (svc optional: app|frontend|caddy)
#   ./deploy.sh health          # show health summaries
#   ./deploy.sh ps              # docker ps for the stack
#   ./deploy.sh --no-cache      # build both w/ no cache
#   ./deploy.sh app --no-cache  # build app w/ no cache

set -Eeuo pipefail

# --- config ---
COMPOSE_FILE="docker-compose.yml"
APP_SVC="app"
FE_SVC="frontend"
CADDY_SVC="caddy"

# --- colors ---
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

# Pick docker compose (new) or docker-compose (legacy)
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f "${COMPOSE_FILE}")
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose -f "${COMPOSE_FILE}")
else
  red "Docker Compose not found. Install Docker Desktop or docker-compose."
  exit 1
fi

# Always run from repo root (script location)
cd "$(dirname "$0")"

# --- parse args ---
svc="all"
no_cache=""

if [[ $# -gt 0 ]]; then
  case "$1" in
    app|frontend|caddy|up|down|logs|health|ps|all)
      svc="$1"
      shift
      ;;
    --no-cache)
      no_cache="--no-cache"
      shift
      ;;
    *)
      red "Unknown command: $1"
      exit 1
      ;;
  esac
fi

# optional flag after command
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--no-cache" ]]; then
    no_cache="--no-cache"
    shift
  else
    red "Unknown option: $1"
    exit 1
  fi
fi

# --- helpers ---
build_and_restart() {
  local service="$1"
  yellow "▶ Building ${service} ${no_cache:+(no-cache)}…"
  "${DC[@]}" build $no_cache "$service"
  yellow "▶ Restarting ${service}…"
  "${DC[@]}" up -d "$service"
}

health() {
  # Uses container_name values from your compose:
  local ids=("vinyl_app" "vinyl_frontend")
  for id in "${ids[@]}"; do
    if docker inspect "$id" >/dev/null 2>&1; then
      local status
      status=$(docker inspect "$id" --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
      if [[ "$status" == "healthy" ]]; then
        green "✓ $id: $status"
      else
        yellow "• $id: $status"
      fi
    else
      yellow "• $id: not running"
    fi
  done
}

logs_cmd() {
  local target="${1:-all}"
  case "$target" in
    all) yellow "▶ Tailing all logs (Ctrl+C to stop)…"; "${DC[@]}" logs -f ;;
    app|frontend|caddy) yellow "▶ Tailing $target logs (Ctrl+C to stop)…"; "${DC[@]}" logs -f "$target" ;;
    *) red "Unknown service for logs: $target"; exit 1 ;;
  esac
}

ps_cmd() {
  "${DC[@]}" ps
}

# --- main ---
case "$svc" in
  all)
    build_and_restart "$APP_SVC"
    build_and_restart "$FE_SVC"
    yellow "▶ Ensuring proxy is up…"
    "${DC[@]}" up -d "$CADDY_SVC"
    health
    ;;
  app)
    build_and_restart "$APP_SVC"
    health
    ;;
  frontend)
    build_and_restart "$FE_SVC"
    health
    ;;
  caddy)
    yellow "▶ Restarting caddy…"
    "${DC[@]}" up -d "$CADDY_SVC"
    ;;
  up)
    yellow "▶ Starting stack…"
    "${DC[@]}" up -d
    health
    ;;
  down)
    yellow "▶ Stopping stack…"
    "${DC[@]}" down
    ;;
  logs)
    logs_cmd "${1:-all}"
    ;;
  health)
    health
    ;;
  ps)
    ps_cmd
    ;;
  *)
    red "Unknown command: $svc"
    exit 1
    ;;
esac