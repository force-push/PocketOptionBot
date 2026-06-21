#!/usr/bin/env bash
# Restart the ArgusSentinel bot cleanly.
#
# launchd + run_supervised.sh is the authoritative supervisor.
# DO NOT run scripts/watchdog.sh manually — it will conflict with launchd.
#
# Usage:
#   tools/restart_bot.sh            # graceful restart (SIGTERM → wait → launchd respawns)
#   tools/restart_bot.sh --hard     # SIGKILL if SIGTERM doesn't work
#
set -euo pipefail
cd "$(dirname "$0")/.."

HARD="${1:-}"
BOT_PID=$(pgrep -f "python.*main_v2\.py" 2>/dev/null | head -1 || true)

if [[ -z "$BOT_PID" ]]; then
    echo "No bot process found. launchd will start it automatically."
    exit 0
fi

echo "Stopping bot PID $BOT_PID..."
if [[ "$HARD" == "--hard" ]]; then
    kill -9 "$BOT_PID" 2>/dev/null || true
else
    kill "$BOT_PID" 2>/dev/null || true
    # Wait up to 15s for graceful shutdown
    for i in $(seq 1 15); do
        kill -0 "$BOT_PID" 2>/dev/null || { echo "Bot stopped after ${i}s."; break; }
        sleep 1
    done
    # Force-kill if still alive
    kill -9 "$BOT_PID" 2>/dev/null || true
fi

echo "Waiting for launchd supervisor (run_supervised.sh) to restart bot..."
sleep 12
NEW_PID=$(pgrep -f "python.*main_v2\.py" 2>/dev/null | head -1 || true)
if [[ -n "$NEW_PID" ]]; then
    echo "Bot restarted as PID $NEW_PID."
else
    echo "WARNING: Bot did not restart within 12s. Check: launchctl list | grep argussentinel"
fi
