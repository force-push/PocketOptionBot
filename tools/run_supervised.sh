#!/usr/bin/env bash
# Watchdog supervisor for main_v2.py.
#
# Two failure modes, both handled:
#   1. CRASH  — process exits → restart after 10s (stderr lands in runtime.log)
#   2. HANG   — process alive but logs/bot.log untouched for STALE_SECS
#               (WS hang: loop dead, background resolutions may still tick)
#               → kill -9, loop restarts it with a fresh WS connection.
#
# Usage:  nohup tools/run_supervised.sh > /dev/null 2>&1 &
cd "$(dirname "$0")/.." || exit 1
STALE_SECS=300
LOG=logs/runtime.log

note() { echo "[supervisor] $(date -u +%FT%TZ) $*" >> "$LOG"; }

note "starting"
while true; do
  .venv/bin/python main_v2.py >> "$LOG" 2>&1 &
  BOT=$!
  note "bot started pid=$BOT"
  LAST_BACKUP=0
  while kill -0 "$BOT" 2>/dev/null; do
    sleep 30
    # Hourly safety-net backup of the decisions log (kept: latest only)
    now=$(date +%s)
    if [ $((now - LAST_BACKUP)) -gt 3600 ] && [ -f data/decisions.jsonl ]; then
      cp data/decisions.jsonl data/decisions.jsonl.bak 2>/dev/null && LAST_BACKUP=$now
    fi
    if [ -f logs/bot.log ]; then
      now=$(date +%s)
      mtime=$(stat -f %m logs/bot.log 2>/dev/null || stat -c %Y logs/bot.log)
      age=$((now - mtime))
      if [ "$age" -gt "$STALE_SECS" ]; then
        note "STALE: bot.log untouched for ${age}s — killing hung bot pid=$BOT"
        kill -9 "$BOT" 2>/dev/null
        break
      fi
    fi
  done
  wait "$BOT" 2>/dev/null
  note "bot exited rc=$? — restarting in 10s"
  sleep 10
done
