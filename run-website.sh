#!/usr/bin/env bash

# run-website.sh
#
# Usage:
#   ./run-website.sh docker   # full site via Docker (vinyl.local)
#   ./run-website.sh local    # full site via local backend + frontend dev
#
# Defaults to 'docker' if no argument is provided.

set -e

MODE="${1:-docker}"

# Resolve project root (directory containing this script)
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_PATH="$ROOT/.venv311"
BACKEND_CONTAINER_NAME="vinyl_app"

start_docker_site() {
  echo "Bringing up Vinyl Record Tracker via Docker…"
  if [ ! -x "./deploy.sh" ]; then
    echo "ERROR: ./deploy.sh not found or not executable in $ROOT"
    exit 1
  fi

  # Build & start app + frontend + caddy
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

start_local_site() {
  echo "Bringing up Vinyl Record Tracker in LOCAL mode…"
  echo "  - Backend: uvicorn (FastAPI) on 127.0.0.1:8000"
  echo "  - Frontend: Vite dev server on localhost:5173"

  # 1) Stop Docker stack so it doesn't conflict
  stop_docker_stack_if_running

  # 2) Check venv
  if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtualenv '$VENV_PATH' not found."
    echo "Create it with:  cd \"$ROOT\" && python3.11 -m venv .venv311"
    exit 1
  fi

  # 3) Start backend (uvicorn) in the background
  # Use the SAME DB as Docker: ./data/records.db -> /app/data/records.db in container
  export VINYL_DB="$ROOT/data/records.db"
  echo "Using database at: $VINYL_DB"

  # Make sure the folder exists
  mkdir -p "$ROOT/data"

  echo "Starting local backend (uvicorn)…"

  (
    cd "$ROOT/app"
    # shellcheck source=/dev/null
    source "$VENV_PATH/bin/activate"
    uvicorn main:app --reload
  ) > "$ROOT/backend-local.log" 2>&1 &

  BACKEND_PID=$!
  echo "Backend PID: $BACKEND_PID (logs: backend-local.log)"

  # Ensure we stop backend when this script is interrupted or exits
  cleanup() {
    echo
    echo "Stopping local backend (PID $BACKEND_PID)…"
    kill "$BACKEND_PID" 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  # 4) Start frontend dev server (foreground)
  cd "$ROOT/frontend"

  if [ ! -d "node_modules" ]; then
    echo "node_modules not found. Running npm install (first time setup)…"
    npm install
  fi

  echo
  echo "Starting frontend dev server…"
  echo "When it says 'Local: http://localhost:5173/', open that in your browser."
  echo

  npm run dev -- --host 0.0.0.0
}

case "$MODE" in
  docker)
    start_docker_site
    ;;
  local)
    start_local_site
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [docker|local]"
    exit 1
    ;;
esac