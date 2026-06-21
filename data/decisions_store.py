"""SQLite store for decision rows — fast writes, indexed reads, clean analysis.

Replaces the append-and-rewrite ``decisions.jsonl`` data path. The old file made
both hot operations O(N) over a growing N:

  * every dashboard request re-parsed the whole file (~4s at 66 MB);
  * every trade resolution (``backfill_outcome``) parsed AND rewrote the whole
    file — ~200×/hour during active trading, quadratic disk churn + .tmp litter.

Here:

  * ``insert_decision``  → one INSERT.
  * ``update_outcome``   → one indexed UPDATE (no rewrite).
  * ``recent_decisions`` / ``find_by_*`` → indexed LIMIT/point queries.
  * ``all_records``      → loads once, then only fetches rows whose ``id`` or
    ``updated_at`` changed since the last call (incremental in-process cache),
    so the existing pure analytics functions get the full list for near-zero
    cost after the first load.

The full original row is kept verbatim in the ``data`` JSON column — nothing is
dropped, so analysis (signal breakdowns, sentiment, shadow_kind, …) is intact;
the promoted columns just make filtering/aggregation fast.

stdlib only (``sqlite3``) → importable and testable fully offline. WAL mode lets
the bot (writer process) and the dashboard (reader process) work concurrently.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

# Columns promoted out of the JSON blob for indexed filtering/sorting. Everything
# else (signal breakdown, balances, probabilities, …) lives in ``data``.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    updated_at    REAL NOT NULL,
    cycle_id      TEXT,
    trade_id      TEXT,
    pair_api      TEXT,
    decision      TEXT,
    skip_reason   TEXT,
    shadow        INTEGER NOT NULL DEFAULT 0,
    shadow_kind   TEXT,
    our_direction TEXT,
    expiry_seconds INTEGER,
    outcome       TEXT,
    pnl           REAL,
    data          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts        ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_decisions_trade     ON decisions(trade_id);
CREATE INDEX IF NOT EXISTS idx_decisions_shadow_ts ON decisions(shadow, ts);
CREATE INDEX IF NOT EXISTS idx_decisions_cycle     ON decisions(cycle_id);
CREATE INDEX IF NOT EXISTS idx_decisions_updated   ON decisions(updated_at);
CREATE INDEX IF NOT EXISTS idx_decisions_pair_ts   ON decisions(pair_api, ts);
"""


# ── connection ────────────────────────────────────────────────────────────────

def connect(path: str | Path) -> sqlite3.Connection:
    """Open a WAL-mode connection with a busy timeout and Row access.

    A fresh connection per logical operation is cheap and side-steps SQLite's
    single-thread connection rule (the dashboard serves requests from a thread
    pool). WAL + busy_timeout let the bot's writes and the dashboard's reads
    overlap without "database is locked" errors.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db(path: str | Path) -> None:
    """Create the table + indexes if absent (idempotent)."""
    with connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


# ── row column extraction ─────────────────────────────────────────────────────

def _promoted(row: dict) -> dict:
    """Pull the indexed columns out of a full decision-row dict."""
    return {
        "ts": row.get("ts") or "",
        "cycle_id": row.get("cycle_id"),
        "trade_id": row.get("trade_id"),
        "pair_api": row.get("pair_api"),
        "decision": row.get("decision"),
        "skip_reason": row.get("skip_reason"),
        "shadow": 1 if row.get("shadow") else 0,
        "shadow_kind": row.get("shadow_kind"),
        "our_direction": row.get("our_direction"),
        "expiry_seconds": row.get("expiry_seconds"),
        "outcome": row.get("outcome"),
        "pnl": row.get("pnl"),
    }


_INSERT_SQL = (
    "INSERT INTO decisions (ts, updated_at, cycle_id, trade_id, pair_api, decision, "
    "skip_reason, shadow, shadow_kind, our_direction, expiry_seconds, outcome, pnl, data) "
    "VALUES (:ts, :updated_at, :cycle_id, :trade_id, :pair_api, :decision, :skip_reason, "
    ":shadow, :shadow_kind, :our_direction, :expiry_seconds, :outcome, :pnl, :data)"
)


def _row_params(row: dict, clock: float) -> dict:
    params = _promoted(row)
    params["updated_at"] = clock
    params["data"] = json.dumps(row, default=str, ensure_ascii=False)
    return params


# ── writes ────────────────────────────────────────────────────────────────────

def insert_decision(path: str | Path, row: dict, *, clock: Optional[float] = None) -> int:
    """Append one decision row. Returns the new rowid."""
    clk = time.time() if clock is None else clock
    with connect(path) as conn:
        cur = conn.execute(_INSERT_SQL, _row_params(row, clk))
        conn.commit()
        return int(cur.lastrowid)


def update_outcome(
    path: str | Path,
    trade_id: str,
    outcome: str,
    pnl: float,
    balance_before: float | None = None,
    balance_after: float | None = None,
    pnl_currency: str | None = None,
    *,
    clock: Optional[float] = None,
) -> bool:
    """Stamp the resolved outcome onto the row(s) for ``trade_id``.

    Updates both the promoted columns and the ``data`` JSON so the full detail
    view reflects the result. One indexed UPDATE per matching row — no file
    rewrite. Returns True if a row was found.
    """
    if not trade_id:
        return False
    clk = time.time() if clock is None else clock
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id, data FROM decisions WHERE trade_id = ?", (trade_id,)
        ).fetchall()
        if not rows:
            return False
        for r in rows:
            d = json.loads(r["data"])
            d.update(
                status=outcome.upper(), outcome=outcome, pnl=pnl,
                balance_before=balance_before, balance_after=balance_after,
                pnl_currency=pnl_currency,
            )
            conn.execute(
                "UPDATE decisions SET outcome = ?, pnl = ?, updated_at = ?, data = ? WHERE id = ?",
                (outcome, pnl, clk, json.dumps(d, default=str, ensure_ascii=False), r["id"]),
            )
        conn.commit()
        return True


# ── point / scoped reads (no full load) ──────────────────────────────────────

def _loads(rows: list[sqlite3.Row]) -> list[dict]:
    return [json.loads(r["data"]) for r in rows]


def recent_decisions(
    path: str | Path, *, limit: int = 100, before: Optional[str] = None,
    since: Optional[str] = None,
) -> list[dict]:
    """Newest-first decision rows (TRADES + SKIPs), for the history view.

    ``before`` is an ISO ts cursor (strictly older). ``since`` is a lower-bound
    ISO ts (inclusive). Fetches only ``limit`` rows.
    """
    if not Path(path).exists():
        return []
    sql = "SELECT data FROM decisions"
    args: list[Any] = []
    clauses: list[str] = []
    if before:
        clauses.append("ts < ?")
        args.append(before.strip())
    if since:
        clauses.append("ts >= ?")
        args.append(since.strip())
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ts DESC"
    if limit is not None and limit >= 0:
        sql += " LIMIT ?"
        args.append(limit)
    with connect(path) as conn:
        return _loads(conn.execute(sql, args).fetchall())


def records_since(path: str | Path, since_iso: Optional[str]) -> list[dict]:
    """All rows with ``ts >= since_iso`` (oldest-first). None → all rows."""
    if not Path(path).exists():
        return []
    if since_iso is None:
        return all_records(path)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT data FROM decisions WHERE ts >= ? ORDER BY ts ASC", (since_iso,)
        ).fetchall()
    return _loads(rows)


def find_by_trade_id(path: str | Path, trade_id: str) -> Optional[dict]:
    if not Path(path).exists():
        return None
    with connect(path) as conn:
        r = conn.execute(
            "SELECT data FROM decisions WHERE trade_id = ? ORDER BY id DESC LIMIT 1",
            (trade_id,),
        ).fetchone()
    return json.loads(r["data"]) if r else None


def find_by_cycle_id(path: str | Path, cycle_id: str) -> Optional[dict]:
    if not Path(path).exists():
        return None
    with connect(path) as conn:
        r = conn.execute(
            "SELECT data FROM decisions WHERE cycle_id = ? ORDER BY id DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
    return json.loads(r["data"]) if r else None


def rolling_pair_rate(
    path: str | Path,
    pair: str,
    *,
    since_iso: str,
    before_iso: str,
) -> tuple[float, int]:
    """Return recent non-shadow pair WR over ``[since_iso, before_iso)``.

    Draws count as non-losses, matching WinRateTracker.rate/pair_rate semantics.
    Pending trades, skips, and shadow rows are excluded.
    """
    if not pair or not Path(path).exists():
        return 0.0, 0
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS n,
              SUM(CASE WHEN outcome IN ('win', 'draw') THEN 1 ELSE 0 END) AS non_losses
            FROM decisions
            WHERE pair_api = ?
              AND shadow = 0
              AND outcome IN ('win', 'loss', 'draw')
              AND ts >= ?
              AND ts < ?
            """,
            (pair, since_iso, before_iso),
        ).fetchone()
    n = int(row["n"] or 0) if row else 0
    if n == 0:
        return 0.0, 0
    return float(row["non_losses"] or 0) / n, n


def tail_outcomes_by_pair(
    path: str | Path,
    *,
    since_iso: str,
    max_per_pair: int = 10,
) -> dict[str, list[str]]:
    """Return the most-recent resolved outcomes per pair since ``since_iso``.

    Returns ``{pair_api: ["win"|"loss"|"draw", ...]}`` newest-first, capped at
    ``max_per_pair``.  Shadow trades and SKIPs are excluded.  Used by
    MartingaleTracker.seed_from_db() to reconstruct loss streaks after a restart.
    """
    if not Path(path).exists():
        return {}
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT pair_api, outcome
            FROM decisions
            WHERE shadow = 0
              AND outcome IN ('win', 'loss', 'draw')
              AND ts >= ?
            ORDER BY ts DESC
            """,
            (since_iso,),
        ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        pair = row["pair_api"]
        if pair and len(result.get(pair, [])) < max_per_pair:
            result.setdefault(pair, []).append(row["outcome"])
    return result


# ── full load (incremental in-process cache) ─────────────────────────────────
# The first call parses every row; later calls fetch only rows whose id is new
# or whose updated_at advanced (outcome backfills), merging into a per-path
# cache keyed by rowid. This keeps the pure analytics functions (which want the
# whole list) fast without re-reading the DB each time.

class _Cache:
    __slots__ = ("by_id", "max_id", "since", "lock")

    def __init__(self) -> None:
        self.by_id: dict[int, dict] = {}
        self.max_id: int = 0
        self.since: float = 0.0  # updated_at high-water mark for change detection
        self.lock = threading.Lock()


# Change detection re-checks rows whose updated_at is within this many seconds
# of the last read. It only needs to exceed the write-commit-to-reader-visible
# latency (~ms) so a concurrent outcome UPDATE can't be skipped between two
# reads; 5s is a large margin. Keeping it small means a warm read re-fetches
# only the handful of rows resolved in the last few seconds (not, say, every row
# a bulk migration stamped at once). New inserts are caught by rowid regardless,
# so only in-place updates lean on this window.
_SAFETY_WINDOW = 5.0

_caches: dict[str, _Cache] = {}
_caches_lock = threading.Lock()


def _cache_for(key: str) -> _Cache:
    with _caches_lock:
        c = _caches.get(key)
        if c is None:
            c = _Cache()
            _caches[key] = c
        return c


def all_records(path: str | Path, *, clock: Optional[float] = None) -> list[dict]:
    """Every decision row, oldest-first by rowid. Incrementally cached.

    The returned dicts are shared cache objects — treat as read-only (all
    analytics consumers project into fresh dicts, matching the old contract).
    """
    p = Path(path)
    if not p.exists():
        return []
    now = time.time() if clock is None else clock
    key = str(p.resolve())
    cache = _cache_for(key)
    with cache.lock:
        with connect(p) as conn:
            rows = conn.execute(
                "SELECT id, data FROM decisions WHERE id > ? OR updated_at >= ? ORDER BY id ASC",
                (cache.max_id, cache.since),
            ).fetchall()
        for r in rows:
            rid = r["id"]
            cache.by_id[rid] = json.loads(r["data"])
            if rid > cache.max_id:
                cache.max_id = rid
        # Rewind the change-detection mark by the safety window (see note above).
        cache.since = now - _SAFETY_WINDOW
        return [cache.by_id[k] for k in sorted(cache.by_id)]


def pair_ev_aggregates(path: str | Path) -> list[dict]:
    """Per-pair win/loss/bot-WR/payout aggregates for resolved TRADE rows.

    Computed entirely in SQL (``GROUP BY pair_api``) so callers never load the
    full decision history into memory — a transient, small result set (one row
    per pair) that is freed immediately. This is the memory-safe replacement for
    ``all_records`` in the trading process's periodic EV-summary log.

    Each dict: ``{pair, w, l, bot_wr, payout}`` where ``payout`` is the average
    live payout% (falling back to back-calculated payout from win pnl/stake when
    ``payout_pct`` wasn't stored). Matches the row filter used previously:
    ``decision='TRADE'`` and ``outcome IN ('win','loss')``.
    """
    p = Path(path)
    if not p.exists():
        return []
    with connect(p) as conn:
        rows = conn.execute(
            """
            SELECT pair_api AS pair,
                   SUM(CASE WHEN outcome IN ('win','draw') THEN 1 ELSE 0 END) AS w,
                   SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS l,
                   AVG(json_extract(data, '$.bot_win_rate')) AS bot_wr,
                   AVG(COALESCE(
                       json_extract(data, '$.payout_pct'),
                       CASE WHEN outcome = 'win' AND pnl IS NOT NULL
                                 AND json_extract(data, '$.stake') > 0
                            THEN pnl / json_extract(data, '$.stake') * 100
                       END)) AS payout
            FROM decisions
            WHERE decision = 'TRADE' AND outcome IN ('win', 'loss', 'draw')
            GROUP BY pair_api
            """
        ).fetchall()
    return [dict(r) for r in rows]


def reset_cache(path: str | Path | None = None) -> None:
    """Drop the in-process cache (tests / after a bulk migration)."""
    with _caches_lock:
        if path is None:
            _caches.clear()
        else:
            _caches.pop(str(Path(path).resolve()), None)


# ── migration ─────────────────────────────────────────────────────────────────

def migrate_jsonl(jsonl_path: str | Path, db_path: str | Path, *, batch: int = 2000) -> int:
    """Bulk-import an existing decisions.jsonl into the DB. Returns rows imported.

    Idempotent only in the sense of being safe to run into a fresh DB; it does
    not dedupe against existing rows, so run it once into an empty store.
    """
    jp = Path(jsonl_path)
    init_db(db_path)
    if not jp.exists():
        return 0
    n = 0
    clk = time.time()
    with connect(db_path) as conn:
        pending: list[dict] = []
        for line in jp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            pending.append(_row_params(row, clk))
            if len(pending) >= batch:
                conn.executemany(_INSERT_SQL, pending)
                n += len(pending)
                pending = []
        if pending:
            conn.executemany(_INSERT_SQL, pending)
            n += len(pending)
        conn.commit()
    reset_cache(db_path)
    return n
