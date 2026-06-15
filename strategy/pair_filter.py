"""Shared pair-eligibility filter — one source of truth for which symbols are
tradable, used by both the poll loop (``manager_v2``) and ``FocusSession`` so
they can never disagree.

Precedence (highest first):
  1. ``ALLOWED_PAIR_REGEX`` — when set, a symbol is allowed only if the pattern
     matches (blocklist still applies). Looser than an exact list and adapts to
     whichever matching crosses are live (e.g. ``(USD|CNY|CNH)``).
  2. ``ALLOWED_PAIRS`` — exact-match allowlist (blocklist ignored for these).
  3. ``BLOCKED_PAIRS`` — default deny-list when no allowlist is configured.
"""
from __future__ import annotations

import re
from typing import Any

from config.settings import settings

# Compile cache keyed by the pattern string (patterns rarely change at runtime).
_compiled: dict[str, re.Pattern | None] = {}


def _regex(pattern: str) -> re.Pattern | None:
    if pattern not in _compiled:
        try:
            _compiled[pattern] = re.compile(pattern) if pattern else None
        except re.error:
            _compiled[pattern] = None  # bad pattern → treat as "no regex"
    return _compiled[pattern]


def is_pair_allowed(symbol: str, cfg: Any = settings) -> bool:
    """Return True if ``symbol`` may be traded under the current config."""
    if not symbol:
        return False
    blocked = set(cfg.blocked_pairs)
    rx = _regex(cfg.allowed_pair_regex)
    if rx is not None:
        return bool(rx.search(symbol)) and symbol not in blocked
    allow = set(cfg.allowed_pairs)
    if allow:
        return symbol in allow
    return symbol not in blocked
