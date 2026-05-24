#!/bin/bash
# Agent dashboard launcher — opens as a clean app-like window
# Uses Firefox Developer Edition (primary browser) with minimal chrome

PORT="${DASHBOARD_PORT:-7788}"
URL="http://127.0.0.1:$PORT"
DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure the server is running
if ! lsof -ti:"$PORT" > /dev/null 2>&1; then
  echo "Starting dashboard server on port $PORT..."
  cd "$DIR" && python3 server.py &
  # Wait until the port is actually listening
  for i in $(seq 1 10); do
    if lsof -ti:"$PORT" > /dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

echo "Opening dashboard at $URL"

# Try Firefox Developer Edition first (user's primary browser), then fallback
if command -v firefox-developer-edition > /dev/null 2>&1; then
  firefox-developer-edition --new-window "$URL" &
elif command -v firefox > /dev/null 2>&1; then
  firefox --new-window "$URL" &
elif command -v chromium > /dev/null 2>&1; then
  chromium --app="$URL" --window-size=1200,750 &
elif command -v google-chrome-stable > /dev/null 2>&1; then
  google-chrome-stable --app="$URL" --window-size=1200,750 &
else
  echo "No supported browser found. Open manually: $URL"
  exit 1
fi
