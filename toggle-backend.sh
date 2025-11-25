#!/usr/bin/env bash

# toggle-backend.sh
#
# Usage:
#   ./toggle-backend.sh          # auto toggle between local and Docker
#   ./toggle-backend.sh local    # force local uvicorn backend (no Docker stack)
#   ./toggle-backend.sh docker   # force Docker backend via ./deploy.sh app
#
# Behavior (auto mode):
# - If local uvicorn backend is running -> stop it and start Docker backend
# - If Docker backend (vinyl_app) is running -> stop it and start local uvicorn backend
# - If neither is running -> start local uvicorn backend

set -e

BACKEND_CONTAINER_NAME="vinyl_app"  # container_name from docker-compose.yml
UVICORN_MATCH="uvicorn main:app"    # how we detect the local uvicorn process
VENV_PATH=".venv311"                # venv relative to project root

project_root() {
  cd "$(dirname "$0")"
  pwd
}

is_uvicorn_running() {
  if pgrep -f "$UVICORN_MATCH" > /dev/null 2>&1; then
    return 0
  else
    return 1
  fi
}

is_docker_backend_running() {
  if docker ps --format '{{.Names}}' | grep -w "$BACKEND_CONTAINER_NAME" > /dev/null 2>&1; then
    return 0
  else
    return 1
  fi
}

stop_uvicorn() {
  echo "Stopping local uvicorn backend..."
  if pgrep -f "$UVICORN_MATCH" > /dev/null 2>&1; then
    pkill -f "$UVICORN_MATCH" || true
  else
    pkill -f "uvicorn" || true
  fi
  sleep 1
}

stop_docker_stack() {
  echo "Stopping Docker stack via ./deploy.sh down ..."
  local ROOT
  ROOT=$(project_root)
  cd "$ROOT"

  if [ ! -x "./deploy.sh" ]; then
    echo "ERROR: ./deploy.sh not found or not executable in $ROOT."
    exit 1
  fi

  ./deploy.sh down
}

stop_docker_backend_only() {
  echo "Stopping Docker backend container: $BACKEND_CONTAINER_NAME ..."
  if docker ps --format '{{.Names}}' | grep -w "$BACKEND_CONTAINER_NAME" > /dev/null 2>&1; then
    docker stop "$BACKEND_CONTAINER_NAME"
  else
    echo "No running container named $BACKEND_CONTAINER_NAME."
  fi
}

start_local_uvicorn() {
  echo "Starting local uvicorn backend with Python 3.11..."

  local ROOT
  ROOT=$(project_root)
  cd "$ROOT"

  export VINYL_DB="$ROOT/app/data/records.db"
  echo "Using database at: $VINYL_DB"

  if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtualenv '$VENV_PATH' not found in $ROOT."
    echo "Create it with:  python3.11 -m venv $VENV_PATH"
    exit 1
  fi

  echo "Activating virtual environment at $VENV_PATH..."
  # shellcheck source=/dev/null
  source "$VENV_PATH/bin/activate"

  cd app
  echo "Launching uvicorn at http://127.0.0.1:8000 ..."
  uvicorn main:app --reload
}

start_docker_backend() {
  echo "Starting Docker backend via ./deploy.sh app ..."

  local ROOT
  ROOT=$(project_root)
  cd "$ROOT"

  if [ ! -x "./deploy.sh" ]; then
    echo "ERROR: ./deploy.sh not found or not executable in $ROOT."
    exit 1
  fi

  ./deploy.sh app
}

MODE="${1:-auto}"   # auto | local | docker

ROOT=$(project_root)
cd "$ROOT"

echo "Project root: $ROOT"
echo "Requested mode: $MODE"

UVICORN_RUNNING=false
DOCKER_RUNNING=false

if is_uvicorn_running; then
  UVICORN_RUNNING=true
fi

if is_docker_backend_running; then
  DOCKER_RUNNING=true
fi

case "$MODE" in
  auto)
    echo "Checking backend status (auto toggle)..."

    if [ "$UVICORN_RUNNING" = true ] && [ "$DOCKER_RUNNING" = true ]; then
      echo "Both local uvicorn and Docker backend appear to be running (unexpected)."
      echo "Stopping Docker backend and keeping local uvicorn..."
      stop_docker_backend_only
      exit 0
    fi

    if [ "$UVICORN_RUNNING" = true ]; then
      echo "Detected: local uvicorn backend is running."
      echo "Toggling to Docker backend..."
      stop_uvicorn
      start_docker_backend
      exit 0
    fi

    if [ "$DOCKER_RUNNING" = true ]; then
      echo "Detected: Docker backend ($BACKEND_CONTAINER_NAME) is running."
      echo "Toggling to local uvicorn backend..."
      stop_docker_backend_only
      start_local_uvicorn
      exit 0
    fi

    echo "No backend detected (neither uvicorn nor Docker)."
    echo "Defaulting to: start local uvicorn backend."
    start_local_uvicorn
    ;;

  local)
    echo "Forcing local uvicorn backend (no Docker stack)..."

    if [ "$DOCKER_RUNNING" = true ]; then
      echo "Docker backend is running; stopping entire Docker stack..."
      stop_docker_stack
    fi

    if [ "$UVICORN_RUNNING" = true ]; then
      echo "Local uvicorn is already running. Nothing to do."
      exit 0
    fi

    start_local_uvicorn
    ;;

  docker)
    echo "Forcing Docker backend via ./deploy.sh app..."

    if [ "$UVICORN_RUNNING" = true ]; then
      echo "Local uvicorn is running; stopping it first..."
      stop_uvicorn
    fi

    # No need to stop entire stack here; deploy.sh app will build+up app.
    start_docker_backend
    ;;

  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [auto|local|docker]"
    exit 1
    ;;
esac