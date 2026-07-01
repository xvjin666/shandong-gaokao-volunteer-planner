#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_PATH="$APP_DIR/data/sample/open_demo.sqlite"
URL="http://127.0.0.1:8765/"

cd "$APP_DIR"
export PYTHONPATH="$APP_DIR/src"

if [ ! -f "$DB_PATH" ]; then
  echo "Building sample SQLite database..."
  python3 -m gaokao_decision.cli build-sample-db --db "$DB_PATH"
fi

echo "Starting local sample server..."
python3 "$APP_DIR/scripts/serve_app.py" --db "$DB_PATH" --host 127.0.0.1 --port 8765 &
SERVER_PID=$!

sleep 2
open "$URL" >/dev/null 2>&1 || true
echo "Started: $URL"
echo "Press Ctrl+C to stop."
wait "$SERVER_PID"
