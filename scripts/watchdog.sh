#!/usr/bin/env bash
# watchdog.sh — monitors PocketOptionBot and restarts it on crash.
#
# Usage:
#   ./scripts/watchdog.sh          # run indefinitely
#   ./scripts/watchdog.sh --once   # one restart cycle only (for testing)
#
# Restart behaviour:
#   - First crash:  restart after 10s
#   - Second crash within 5 min: restart after 30s
#   - Third+ within 5 min: restart after 120s (cap)
#   - If bot runs cleanly for 5+ min, backoff resets
#
# Logs:
#   logs/watchdog.log  — restart events, exit codes, timestamps
#
# Stop:
#   kill $(cat logs/watchdog.pid)   or   Ctrl-C

set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$BOT_DIR/logs"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
PID_FILE="$LOG_DIR/watchdog.pid"
PYTHON="$BOT_DIR/.venv/bin/python3"
ENTRY="$BOT_DIR/main_v2.py"

BACKOFF_RESET_SECS=300   # clean run longer than this → reset backoff
MAX_BACKOFF=120
ONCE="${1:-}"

mkdir -p "$LOG_DIR"
echo $$ > "$PID_FILE"

log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $*" | tee -a "$WATCHDOG_LOG"
}

cleanup() {
    log "Watchdog stopping (signal received). Killing bot PID ${BOT_PID:-none}."
    [[ -n "${BOT_PID:-}" ]] && kill "$BOT_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 0
}
trap cleanup INT TERM

log "=== Watchdog started (PID $$, bot: $ENTRY) ==="

backoff=10
crash_window_start=0
crashes_in_window=0
BOT_PID=""

while true; do
    start_ts=$(date +%s)
    log "Starting bot…"

    # Run bot; tee output so it still goes to the normal bot log path
    "$PYTHON" "$ENTRY" 2>&1 | tee -a "$LOG_DIR/bot.log" &
    BOT_PID=$!
    wait "$BOT_PID" || true
    exit_code=$?
    BOT_PID=""

    end_ts=$(date +%s)
    run_secs=$(( end_ts - start_ts ))

    log "Bot exited (code=$exit_code, ran ${run_secs}s)."

    [[ "$ONCE" == "--once" ]] && { log "--once flag set, exiting."; rm -f "$PID_FILE"; exit 0; }

    # Reset backoff if bot ran cleanly for a while
    if (( run_secs >= BACKOFF_RESET_SECS )); then
        backoff=10
        crash_window_start=$end_ts
        crashes_in_window=1
        log "Clean run (${run_secs}s ≥ ${BACKOFF_RESET_SECS}s). Backoff reset to ${backoff}s."
    else
        # Check if we're still within the crash window
        if (( end_ts - crash_window_start <= BACKOFF_RESET_SECS )); then
            crashes_in_window=$(( crashes_in_window + 1 ))
        else
            crash_window_start=$end_ts
            crashes_in_window=1
            backoff=10
        fi

        if (( crashes_in_window >= 3 )); then
            backoff=$MAX_BACKOFF
        elif (( crashes_in_window == 2 )); then
            backoff=30
        fi

        log "Crash #${crashes_in_window} in window. Restarting in ${backoff}s…"
    fi

    sleep "$backoff"
done
