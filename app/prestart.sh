#!/usr/bin/env bash
set -e
# Ensure Python deps are present before Gunicorn starts
if [ -f /app/requirements.txt ]; then
  python -m pip install --no-cache-dir -r /app/requirements.txt
fi
