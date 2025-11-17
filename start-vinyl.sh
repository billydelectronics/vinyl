#!/usr/bin/env bash
#
# start-vinyl.sh — one-command launcher for the Vinyl app stack
#

set -e

cd "$(dirname "$0")"

echo "🎵 Starting Vinyl web app..."

# 1. Ensure Docker is running
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker does not appear to be running. Please start Docker Desktop or 'sudo systemctl start docker'."
  exit 1
fi

# 2. Ensure data & covers directories exist with open perms
mkdir -p ./data ./covers
chmod 777 ./data ./covers

# 3. Bring up containers (they’ll reuse cached images if no changes)
echo "🚀 Launching containers..."
docker compose up -d app frontend caddy

# 4. Wait a few seconds for the services to start
echo "⏳ Waiting for services to start..."
sleep 5

# 5. Check health of each container
echo "🔍 Checking container status..."
docker compose ps

# 6. Optionally check logs for issues
echo
echo "📜 Checking quick logs for errors..."
docker compose logs --tail=10 app | grep -iE "error|failed" && echo "⚠️  Some errors above" || echo "✅ App logs look OK"
docker compose logs --tail=10 frontend | grep -iE "error|failed" && echo "⚠️  Some errors above" || echo "✅ Frontend logs look OK"
docker compose logs --tail=10 caddy | grep -iE "error|failed" && echo "⚠️  Some errors above" || echo "✅ Caddy logs look OK"

# 7. Try an API ping
echo
echo "🌐 Testing API endpoint..."
if curl -s -f http://localhost/api/records >/dev/null; then
  echo "✅ API reachable at http://localhost/api/records"
else
  echo "⚠️  Could not reach API at http://localhost/api/records"
fi

# 8. Open browser if available
if command -v open >/dev/null; then
  echo "🌎 Opening http://localhost in your browser..."
  open "http://localhost"
elif command -v xdg-open >/dev/null; then
  xdg-open "http://localhost" >/dev/null 2>&1 &
  echo "🌎 Opening in browser..."
else
  echo "🌎 Visit: http://localhost"
fi

echo
echo "✅ Vinyl app should now be running!"
echo "Use 'docker compose logs -f' to watch logs or 'docker compose down' to stop everything."