#!/usr/bin/env bash

# -----------------------------------------
# Stop Docker backend container if running
# -----------------------------------------

echo "Checking for running Docker backend container..."

BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -i 'backend' || true)

if [ -n "$BACKEND_CONTAINER" ]; then
    echo "Stopping container: $BACKEND_CONTAINER"
    docker stop "$BACKEND_CONTAINER"
else
    echo "No backend Docker container is currently running."
fi

# -----------------------------------------
# Start local uvicorn backend
# -----------------------------------------

echo "Starting local FastAPI backend using Python 3.11…"

# Move to the project root (directory this script is in)
cd "$(dirname "$0")"

# Point to the correct DB path
export VINYL_DB="$(pwd)/app/data/records.db"
echo "Using database at: $VINYL_DB"

# Activate your Python 3.11 virtual environment
if [ ! -d ".venv311" ]; then
    echo "ERROR: .venv311 not found in $(pwd)."
    echo "Did you create it with:  python3.11 -m venv .venv311 ?"
    exit 1
fi

echo "Activating virtual environment…"
source .venv311/bin/activate

# Start uvicorn from the /app directory
cd app
echo "Launching uvicorn at http://127.0.0.1:8000 ..."
uvicorn main:app --reload