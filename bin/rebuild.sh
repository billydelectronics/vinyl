#!/usr/bin/env bash
# Rebuild & restart the Vinyl stack (frontend + backend + caddy)
# Usage:
#   ./bin/rebuild.sh                # full rebuild (no cache purge)
#   ./bin/rebuild.sh frontend       # rebuild only frontend
#   ./bin/rebuild.sh backend        # rebuild only backend (app)
#   ./bin/rebuild.sh caddy          # rebuild only caddy
#   NOCACHE=1 ./bin/rebuild.sh      # build with --no-cache
#   PRUNE=1  ./bin/rebuild.sh       # prune builder cache before build
#   PULL=1   ./bin/rebuild.sh       # docker compose build --pull
set -euo pipefail

# ---- config ---------------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="${PROJECT_ROOT}/docker-compose.yml"
SERVICES_ALL=("frontend" "app" "caddy")
TARGETS=("${@:-all}")
NO_CACHE_FLAG=${NOCACHE:-0}
PRUNE_FLAG=${PRUNE:-0}
PULL_FLAG=${PULL:-0}

# ---- helpers --------------------------------------------------------------
say() { printf "\033[1;36m[rebuild]\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m[rebuild]\033[0m %s\n" "$*" >&2; }

need() { command -v "$1" >/dev/null 2>&1 || { err "Missing '$1'"; exit 1; }; }

is_running() { docker info >/dev/null 2>&1; }

# ---- preflight ------------------------------------------------------------
need docker
need docker compose

if ! is_running; then
  err "Docker is not running. Start Docker Desktop and retry."
  exit 1
fi

if [[ ! -f "$COMPOSE" ]]; then
  err "docker-compose.yml not found at $COMPOSE"
  exit 1
fi

cd "$PROJECT_ROOT"

# ---- resolve targets ------------------------------------------------------
case "${TARGETS[*]}" in
  all)
    SERVICES=("${SERVICES_ALL[@]}")
    ;;
  *)
    SERVICES=("${TARGETS[@]}")
    ;;
esac

# validate services
for s in "${SERVICES[@]}"; do
  case "$s" in
    frontend|app|caddy) : ;;
    *)
      err "Unknown service '$s'. Valid: frontend, app, caddy, or 'all'"
      exit 1
      ;;
  esac
done

# ---- stop stack (only when rebuilding all) --------------------------------
if [[ "${SERVICES[*]}" == "${SERVICES_ALL[*]}" ]]; then
  say "Stopping stack…"
  docker compose down || true
fi

# ---- optional prune -------------------------------------------------------
if [[ "$PRUNE_FLAG" == "1" ]]; then
  say "Pruning builder cache…"
  docker builder prune -f
fi

# ---- build ----------------------------------------------------------------
BUILD_FLAGS=()
[[ "$NO_CACHE_FLAG" == "1" ]] && BUILD_FLAGS+=("--no-cache")
[[ "$PULL_FLAG"    == "1" ]] && BUILD_FLAGS+=("--pull")

say "Building services: ${SERVICES[*]} ${BUILD_FLAGS[*]}"
docker compose build "${BUILD_FLAGS[@]}" "${SERVICES[@]}"

# ---- start ----------------------------------------------------------------
say "Starting services: ${SERVICES[*]} (force recreate)"
docker compose up -d --force-recreate "${SERVICES[@]}"

# ---- post-checks ----------------------------------------------------------
say "Containers:"
docker compose ps

# quick health pings (best-effort)
say "Health checks:"
if printf "%s\n" "${SERVICES[@]}" | grep -q "^frontend$"; then
  curl -sS -I http://localhost/ | sed -n '1,3p' || true
fi
if printf "%s\n" "${SERVICES[@]}" | grep -q "^app$"; then
  curl -sS -I http://localhost/openapi.json | sed -n '1,3p' || true
fi

say "Done ✅"