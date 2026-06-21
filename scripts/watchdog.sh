#!/usr/bin/env bash
# watchdog.sh — DEPRECATED. DO NOT RUN THIS MANUALLY.
#
# The bot is managed by launchd via tools/run_supervised.sh.
# Running this script alongside launchd causes constant bot stops because
# it kills existing bot processes (pgrep | xargs kill) on startup, and
# each time it is killed it takes the bot with it.
#
# To restart the bot: tools/restart_bot.sh
# To check status:    launchctl list | grep argussentinel
# To reload launchd:  launchctl kickstart -k gui/$(id -u)/com.kym.argussentinel
#
# Original usage (historical, no longer valid):
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
BOT_PID_FILE="$LOG_DIR/bot.pid"
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

# Kill a process and wait up to TIMEOUT seconds for it to die
kill_and_wait() {
    local pid="$1" timeout="${2:-10}" label="${3:-process}"
    [[ -z "$pid" ]] && return 0
    kill "$pid" 2>/dev/null || return 0
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        (( i++ >= timeout )) && { log "WARN: $label PID $pid still alive after ${timeout}s, sending SIGKILL"; kill -9 "$pid" 2>/dev/null || true; break; }
        sleep 1
    done
}

cleanup() {
    log "Watchdog stopping (signal received). Killing bot PID ${PYTHON_PID:-none}."
    kill_and_wait "${PYTHON_PID:-}" 10 "bot"
    rm -f "$PID_FILE" "$BOT_PID_FILE"
    exit 0
}
trap cleanup INT TERM

# Kill any stale bot instances from prior watchdog sessions
log "=== Watchdog started (PID $$, bot: $ENTRY) ==="
stale=$(pgrep -f "python.*main_v2\.py" 2>/dev/null || true)
if [[ -n "$stale" ]]; then
    log "Killing stale bot instance(s): $stale"
    echo "$stale" | xargs kill 2>/dev/null || true
    sleep 3
fi

backoff=10
crash_window_start=0
crashes_in_window=0
PYTHON_PID=""
TEE_PID=""

while true; do
    start_ts=$(date +%s)
    log "Starting bot…"

    # Run bot; capture Python PID separately from tee
    "$PYTHON" "$ENTRY" > >(tee -a "$LOG_DIR/bot.log") 2>&1 &
    PYTHON_PID=$!
    echo "$PYTHON_PID" > "$BOT_PID_FILE"
    wait "$PYTHON_PID" || true
    exit_code=$?
    rm -f "$BOT_PID_FILE"
    PYTHON_PID=""

    end_ts=$(date +%s)
    run_secs=$(( end_ts - start_ts ))

    log "Bot exited (code=$exit_code, ran ${run_secs}s)."

    # Ensure no orphaned bot processes remain before restarting
    orphans=$(pgrep -f "python.*main_v2\.py" 2>/dev/null || true)
    if [[ -n "$orphans" ]]; then
        log "Killing orphaned bot process(es): $orphans"
        echo "$orphans" | xargs kill 2>/dev/null || true
        sleep 2
    fi

    [[ "$ONCE" == "--once" ]] && { log "--once flag set, exiting."; rm -f "$PID_FILE" "$BOT_PID_FILE"; exit 0; }

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
