#!/usr/bin/env bash
# ---------------------------------------------------------------
# VinylShelf Dev Runner
# Starts the stack in development mode with backend auto-reload
# ---------------------------------------------------------------

set -e

echo "🚀 Starting Vinyl dev environment (backend auto-reload enabled)..."
echo

# Rebuild and start containers with dev overrides (or profiles)
docker compose --profile dev up -d --build

echo
echo "✅ Containers are running."
echo "---------------------------------------------------------------"
echo "Frontend:  http://localhost"
echo "API Docs:  http://localhost/docs"
echo "---------------------------------------------------------------"
echo
echo "To view logs: docker compose logs -f app"
echo "To stop:      docker compose down"