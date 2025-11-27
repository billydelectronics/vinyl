#!/usr/bin/env bash

# run-website.sh
#
# Usage:
#   ./run-website.sh docker      # full site via Docker (vinyl.local)
#   ./run-website.sh local       # local backend + frontend dev (slow, reload)
#   ./run-website.sh local-prod  # local backend (fast) + built frontend (fast)
#
# Defaults to 'docker' if no argument is provided.

set -e

MODE="${1:-docker}"

# Resolve project root (directory containing this script)
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Load .env if present (for DISCOGS_TOKEN, etc.)
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

VENV_PATH="$ROOT/.venv311"
BACKEND_CONTAINER_NAME="vinyl_app"

start_docker_site() {
  echo "Bringing up Vinyl Record Tracker via Docker…"
  if [ ! -x "./deploy.sh" ]; then
    echo "ERROR: ./deploy.sh not found or not executable in $ROOT"
    exit 1
  fi

  ./deploy.sh all

  echo
  echo "✅ Docker site is starting up."
  echo "   Browse at: http://vinyl.local"
}

stop_docker_stack_if_running() {
  echo "Stopping Docker stack if running…"
  if [ -x "./deploy.sh" ]; then
    ./deploy.sh down || true
  fi
}

# ------------------------------------------------------------------------------
# LOCAL (DEV MODE)
# ------------------------------------------------------------------------------
start_local_site() {
  echo "Bringing up Vinyl Record Tracker in LOCAL DEV mode…"
  echo "  - Backend: uvicorn --reload (slow)"
  echo "  - Frontend: Vite dev server (slow)"

  stop_docker_stack_if_running

  if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtualenv '$VENV_PATH' not found."
    echo "Create it with:  cd \"$ROOT\" && python3.11 -m venv .venv311"
    exit 1
  fi

  export VINYL_DB="$ROOT/data/records.db"
  export CLIP_MODEL_NAME="ViT-L/14@336px"
  export USER_AGENT="VinylRecordTracker/1.0"
  export REQUEST_TIMEOUT="20"
  mkdir -p "$ROOT/data"

  echo "Starting local backend (uvicorn --reload)…"

  (
    cd "$ROOT/app"
    source "$VENV_PATH/bin/activate"
    uvicorn main:app --reload
  ) > "$ROOT/backend-local.log" 2>&1 &

  BACKEND_PID=$!
  echo "Backend PID: $BACKEND_PID (logs: backend-local.log)"

  cleanup() {
    echo
    echo "Stopping local backend (PID $BACKEND_PID)…"
    kill "$BACKEND_PID" 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  cd "$ROOT/frontend"

  if [ ! -d "node_modules" ]; then
    echo "node_modules not found. Running npm install…"
    npm install
  fi

  echo
  echo "Starting Vite dev server…"
  echo "Open: http://localhost:5173/"
  echo

  npm run dev -- --host 0.0.0.0
}

# ------------------------------------------------------------------------------
# LOCAL-PROD (FAST MODE)
# ------------------------------------------------------------------------------
start_local_prod_site() {
  echo "Bringing up Vinyl Record Tracker in LOCAL-PROD mode…"
  echo "  - Backend: uvicorn (no reload, fast)"
  echo "  - Frontend: built + preview (fast, like Docker)"

  stop_docker_stack_if_running

  if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtualenv '$VENV_PATH' not found."
    echo "Create it with:  cd \"$ROOT\" && python3.11 -m venv .venv311"
    exit 1
  fi

  export VINYL_DB="$ROOT/data/records.db"
  export CLIP_MODEL_NAME="ViT-L/14@336px"
  # export CLIP_MODEL_NAME="ViT-B/32"
  # Force MPS in case torch ever defaults to CPU
  export CLIP_DEVICE="mps"
  export USER_AGENT="VinylRecordTracker/1.0"
  export REQUEST_TIMEOUT="20"
  mkdir -p "$ROOT/data"

  echo "Starting local backend (uvicorn, NO reload)…"

  (
    cd "$ROOT/app"
    source "$VENV_PATH/bin/activate"
    uvicorn main:app --host 0.0.0.0 --port 8000
  ) > "$ROOT/backend-local.log" 2>&1 &

  BACKEND_PID=$!
  echo "Backend PID: $BACKEND_PID (logs: backend-local.log)"

  cleanup() {
    echo
    echo "Stopping local backend (PID $BACKEND_PID)…"
    kill "$BACKEND_PID" 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  cd "$ROOT/frontend"

  if [ ! -d "node_modules" ]; then
    echo "node_modules not found. Running npm install…"
    npm install
  fi

  echo
  echo "Building frontend (npm run build)…"
  npm run build

  echo
  echo "Starting frontend preview server (fast)…"
  echo "Open: http://localhost:5173/"
  echo

  npm run preview -- --host 0.0.0.0 --port 5173
}

# ------------------------------------------------------------------------------
# MODE HANDLER
# ------------------------------------------------------------------------------
case "$MODE" in
  docker)
    start_docker_site
    ;;
  local)
    start_local_site
    ;;
  local-prod)
    start_local_prod_site
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [docker|local|local-prod]"
    exit 1
    ;;
esac