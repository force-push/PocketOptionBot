#!/usr/bin/env bash
#
# Run the PocketOption Bot web dashboard locally — no SSID, Telegram, or network
# trading required. Creates a virtualenv, installs the minimal dashboard deps,
# seeds synthetic demo data, and starts the server.
#
#   ./scripts/run_dashboard.sh             # seed fresh demo data + run
#   ./scripts/run_dashboard.sh --no-seed   # keep existing data, just run
#
# Then open http://127.0.0.1:8787  (override with DASHBOARD_PORT=9000 ...).
#
# macOS / Linux / WSL / Git-Bash. On native Windows PowerShell, follow the manual
# steps in the README "Web Dashboard" section instead.
set -euo pipefail

# always run from the repo root (this script lives in scripts/)
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "✗ '$PYTHON' not found. Install Python 3.9+ or set PYTHON=/path/to/python." >&2
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "▸ creating virtualenv ($VENV) …"
  "$PYTHON" -m venv "$VENV"
fi

# activate (POSIX venv uses bin/, Windows venv uses Scripts/)
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
else
  # shellcheck disable=SC1091
  source "$VENV/Scripts/activate"
fi

echo "▸ installing dashboard dependencies …"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r requirements-dashboard.txt

if [ "${1:-}" != "--no-seed" ]; then
  echo "▸ seeding synthetic demo data (data/decisions.jsonl, data/live_state.json) …"
  "$PYTHON" tools/dashboard_demo.py
fi

PORT="${DASHBOARD_PORT:-8787}"
echo ""
echo "  ✔ dashboard ready → http://127.0.0.1:${PORT}"
echo "    (Ctrl-C to stop)"
echo ""
exec python -m dashboard.server
