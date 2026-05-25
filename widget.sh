#!/usr/bin/env bash
# Agent dashboard launcher — opens as a clean widget/app window.
# Works on macOS and Linux. Windows uses widget.ps1.

PORT="${DASHBOARD_PORT:-7788}"
URL="http://127.0.0.1:$PORT"
DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE_DIR="${TMPDIR:-/tmp}/agent-dashboard-widget-profile"

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

# Prefer Chromium-family app mode for consistent widget chrome across OSes.
APP_ARGS=(
  "--app=$URL"
  "--window-size=1200,750"
  "--window-position=80,80"
  "--disable-extensions"
  "--no-first-run"
  "--user-data-dir=$PROFILE_DIR"
)

if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ -d "/Applications/Google Chrome.app" ]]; then
    open -na "Google Chrome" --args "${APP_ARGS[@]}"
  elif [[ -d "/Applications/Microsoft Edge.app" ]]; then
    open -na "Microsoft Edge" --args "${APP_ARGS[@]}"
  elif [[ -d "/Applications/Chromium.app" ]]; then
    open -na "Chromium" --args "${APP_ARGS[@]}"
  else
    echo "No Chrome/Edge/Chromium app found. Open manually: $URL"
    exit 1
  fi
elif command -v google-chrome > /dev/null 2>&1; then
  google-chrome "${APP_ARGS[@]}" &
elif command -v google-chrome-stable > /dev/null 2>&1; then
  google-chrome-stable "${APP_ARGS[@]}" &
elif command -v chromium > /dev/null 2>&1; then
  chromium "${APP_ARGS[@]}" &
elif command -v chromium-browser > /dev/null 2>&1; then
  chromium-browser "${APP_ARGS[@]}" &
elif command -v microsoft-edge > /dev/null 2>&1; then
  microsoft-edge "${APP_ARGS[@]}" &
else
  echo "No Chrome/Edge/Chromium-compatible browser found. Open manually: $URL"
  exit 1
fi
