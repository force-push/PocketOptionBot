"""Settings read/write for the dashboard Settings tab.

Dependency-free except pydantic (and python-dotenv for the actual ``.env``
write). Responsibilities (docs/dashboard-plan.md §4.2 POST rules + §1 security):

- Read the current settings, **grouped** to mirror the mockup, with secret
  fields masked (``"••••"``) — secrets are NEVER echoed back.
- Validate a partial update by constructing ``BotSettings`` (so every field goes
  through the same validators the bot uses) before writing.
- Write accepted values to ``.env`` via ``python-dotenv``'s ``set_key`` (which
  preserves the other keys).
- Enforce the LIVE/SSID guard: flipping ``TRADE_MODE`` to LIVE requires
  ``confirm_live=True`` AND the configured SSID must parse as live — otherwise
  the update is rejected (fail-closed). Never silently apply.

The pure pieces (masking, grouping, SSID demo decode, the LIVE guard, partial
update validation) work with stdlib only. Field-level validation is delegated to
``BotSettings``; it's resolved lazily so this module imports without pydantic and
its pure logic stays unit-testable offline. Tests may inject a ``validator``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

MASK = "••••"

# ── field catalogue ──────────────────────────────────────────────────────────
# (env_var, settings_attr, group, type, secret, requires_restart, label)
# Mirrors the mockup's groups: Safety/Mode, Telegram, PocketOption WS, Signal
# Gate, Risk. ``requires_restart`` flags fields the running bot won't hot-reload.

class _F:
    __slots__ = ("env", "attr", "group", "kind", "secret", "requires_restart", "label")

    def __init__(self, env, attr, group, kind, secret, requires_restart, label):
        self.env = env
        self.attr = attr
        self.group = group
        self.kind = kind  # "str" | "int" | "float" | "bool"
        self.secret = secret
        self.requires_restart = requires_restart
        self.label = label


FIELDS: list[_F] = [
    # Safety / Mode
    _F("TRADE_MODE", "trade_mode", "Safety & Trade Mode", "str", False, True, "Trade Mode"),
    _F("DRY_RUN", "dry_run", "Safety & Trade Mode", "bool", False, False, "Dry Run"),
    _F("STAKE_AMOUNT", "stake_amount", "Safety & Trade Mode", "float", False, False, "Stake Amount (USD)"),
    _F("DEFAULT_EXPIRY_SECONDS", "default_expiry_seconds", "Safety & Trade Mode", "int", False, False, "Default Expiry (s)"),
    # Telegram
    _F("TELEGRAM_API_ID", "telegram_api_id", "Telegram", "int", False, True, "API ID"),
    _F("TELEGRAM_API_HASH", "telegram_api_hash", "Telegram", "str", True, True, "API Hash"),
    _F("SIGNAL_BOT_USERNAME", "signal_bot_username", "Telegram", "str", False, True, "Signal Bot"),
    # PocketOption WS
    _F("PO_SSID", "po_ssid", "PocketOption WS", "str", True, True, "SSID"),
    # Signal Gate
    _F("PAIR_SELECT_MIN_WIN_RATE", "pair_select_min_win_rate", "Signal Gate", "float", False, False, "Min Win Rate"),
    _F("MIN_CONFLUENCE_SCORE", "min_confluence_score", "Signal Gate", "float", False, False, "Min Confluence"),
    _F("CLICK_TRADE_ANYWAY", "click_trade_anyway", "Signal Gate", "bool", False, False, "Click Trade Anyway"),
    # Risk
    _F("MAX_TRADES_PER_HOUR", "max_trades_per_hour", "Risk", "int", False, True, "Max Trades / Hour"),
    _F("MAX_DAILY_LOSS_USD", "max_daily_loss_usd", "Risk", "float", False, True, "Daily Loss Limit (USD)"),
    _F("COOLDOWN_AFTER_LOSS_SECONDS", "cooldown_after_loss_seconds", "Risk", "int", False, True, "Post-Loss Cooldown (s)"),
    _F("MIN_BALANCE_MULTIPLIER", "min_balance_multiplier", "Risk", "float", False, True, "Min Balance Multiplier"),
]

_BY_ENV = {f.env: f for f in FIELDS}
_BY_ATTR = {f.attr: f for f in FIELDS}
SECRET_ENVS = {f.env for f in FIELDS if f.secret}


# ── SSID demo/live decode (ported from broker/po_api.py, stdlib only) ─────────

def ssid_is_demo(ssid: str) -> Optional[bool]:
    """Decode the ``isDemo`` flag from an SSID string.

    Returns True (demo), False (live), or None when unparseable/empty. Matches
    ``broker.po_api._parse_ssid_is_demo`` so the dashboard agrees with the bot.
    """
    if not ssid:
        return None
    try:
        m = re.search(r"\[.*?,\s*(\{.*\})\s*\]", ssid, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(1))
        is_demo = obj.get("isDemo")
        if is_demo is None:
            return None
        return bool(is_demo)
    except Exception:
        return None


# ── read (masked, grouped) ───────────────────────────────────────────────────

def _coerce_display(value: Any, field: _F) -> Any:
    if field.secret:
        # mask any non-empty secret; empty stays empty so the UI shows "unset"
        return MASK if value not in (None, "") else ""
    return value


def read_settings(settings_obj: Any) -> dict:
    """Return the grouped, secret-masked settings snapshot for the UI.

    Shape::

        {"groups": {<group>: [{"env","attr","label","value","type","secret",
                               "requires_restart"}, ...]},
         "detected": {"ssid_mode": "DEMO"|"LIVE"|"UNKNOWN"}}

    Secrets are masked; their real values are never returned.
    """
    groups: dict[str, list] = {}
    for f in FIELDS:
        raw = getattr(settings_obj, f.attr, None)
        # trade_mode is a StrEnum; render its value
        if f.attr == "trade_mode" and raw is not None:
            raw = getattr(raw, "value", str(raw))
        groups.setdefault(f.group, []).append({
            "env": f.env,
            "attr": f.attr,
            "label": f.label,
            "value": _coerce_display(raw, f),
            "type": f.kind,
            "secret": f.secret,
            "requires_restart": f.requires_restart,
        })

    ssid = getattr(settings_obj, "po_ssid", "") or ""
    demo = ssid_is_demo(ssid)
    ssid_mode = "UNKNOWN" if demo is None else ("DEMO" if demo else "LIVE")

    return {"groups": groups, "detected": {"ssid_mode": ssid_mode}}


# ── value coercion for incoming updates ──────────────────────────────────────

def _coerce_incoming(value: Any, kind: str) -> Any:
    """Best-effort coerce a JSON value to the field's python type.

    Real validation happens via BotSettings; this just normalises obvious forms
    (e.g. "true"/"1" → bool) so dotenv writes sane strings.
    """
    if kind == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"not a boolean: {value!r}")
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return value if value is None else str(value)


def _env_str(value: Any, kind: str) -> str:
    if kind == "bool":
        return "true" if value else "false"
    return str(value)


# ── validation + LIVE guard ──────────────────────────────────────────────────

def _default_validator(env_overrides: dict[str, str]) -> None:
    """Construct BotSettings with the proposed env values to validate them.

    Raises if any field is invalid. Resolved lazily so this module imports
    without pydantic.
    """
    from config.settings import BotSettings  # lazy: keeps module dep-free to import

    # Build kwargs keyed by env alias (BotSettings fields use uppercase aliases).
    BotSettings(**env_overrides)


def validate_update(
    fields: dict[str, Any],
    *,
    settings_obj: Any,
    confirm_live: bool = False,
    validator: Optional[Callable[[dict[str, str]], None]] = None,
) -> dict:
    """Validate a partial update WITHOUT writing.

    Returns ``{"ok", "applied", "errors", "requires_restart"}``.

    - Every field name must be a known env var; unknown → error.
    - Secret fields whose value equals the mask (or empty) are ignored (not an
      update) — secrets are only written when a real value is supplied.
    - Each value is coerced and then the whole proposed config is validated by
      constructing ``BotSettings`` (the same validators the bot uses).
    - LIVE guard: setting ``TRADE_MODE=LIVE`` requires ``confirm_live=True`` AND
      the *resulting* SSID must decode as live; otherwise rejected.
    """
    errors: dict[str, str] = {}
    accepted: dict[str, Any] = {}   # env -> coerced python value (to apply/write)

    for name, value in (fields or {}).items():
        env = name if name in _BY_ENV else None
        if env is None and name in _BY_ATTR:
            env = _BY_ATTR[name].env
        if env is None:
            errors[name] = "unknown setting"
            continue
        f = _BY_ENV[env]

        # secrets: skip mask/empty (means "leave unchanged")
        if f.secret and (value in (None, "", MASK)):
            continue

        try:
            coerced = _coerce_incoming(value, f.kind)
        except (ValueError, TypeError) as exc:
            errors[env] = f"invalid value: {exc}"
            continue
        accepted[env] = coerced

    if errors:
        return {"ok": False, "applied": {}, "errors": errors, "requires_restart": []}

    # ── LIVE/SSID guard (fail-closed) ────────────────────────────────────────
    new_mode = accepted.get("TRADE_MODE")
    if new_mode is not None and str(new_mode).strip().upper() == "LIVE":
        if not confirm_live:
            errors["TRADE_MODE"] = (
                "Flipping to LIVE requires explicit confirmation (confirm_live=true)."
            )
        else:
            # SSID that WOULD be in effect after this update.
            effective_ssid = accepted.get("PO_SSID", getattr(settings_obj, "po_ssid", "") or "")
            demo = ssid_is_demo(effective_ssid)
            if demo is None:
                errors["TRADE_MODE"] = (
                    "Cannot enable LIVE: SSID is missing or could not be decoded "
                    "(isDemo unknown). Refusing to flip LIVE (fail-closed)."
                )
            elif demo is True:
                errors["TRADE_MODE"] = (
                    "Cannot enable LIVE: configured SSID is a DEMO account "
                    "(isDemo=1). Provide a live SSID first."
                )
        if errors:
            return {"ok": False, "applied": {}, "errors": errors, "requires_restart": []}

    # ── field validation via BotSettings ─────────────────────────────────────
    env_overrides = {env: _env_str(val, _BY_ENV[env].kind) for env, val in accepted.items()}
    vfn = validator or _default_validator
    try:
        vfn(env_overrides)
    except Exception as exc:  # pydantic ValidationError / SettingsError / ValueError
        # surface a compact, secret-free message
        return {
            "ok": False,
            "applied": {},
            "errors": {"_": _safe_error(exc)},
            "requires_restart": [],
        }

    applied = {}
    for env in accepted:
        f = _BY_ENV[env]
        applied[env] = MASK if f.secret else accepted[env]
    requires_restart = sorted({env for env in accepted if _BY_ENV[env].requires_restart})

    return {
        "ok": True,
        "applied": applied,
        "errors": {},
        "requires_restart": requires_restart,
        # internal: env-string values to persist (not echoed to clients verbatim
        # for secrets — caller writes these but the response masks them)
        "_env_overrides": env_overrides,
    }


def _safe_error(exc: Exception) -> str:
    """Compact error text with any secret env names/values stripped."""
    msg = str(exc)
    for env in SECRET_ENVS:
        msg = msg.replace(env, env)  # keep env name but never include its value
    # pydantic errors can include the offending input; truncate to be safe.
    return msg.splitlines()[0][:300] if msg else exc.__class__.__name__


# ── write (.env via python-dotenv set_key) ───────────────────────────────────

def apply_update(
    fields: dict[str, Any],
    *,
    settings_obj: Any,
    env_path: str | Path,
    confirm_live: bool = False,
    validator: Optional[Callable[[dict[str, str]], None]] = None,
) -> dict:
    """Validate then persist a partial update to ``.env``.

    Returns the same shape as ``validate_update`` (without the private
    ``_env_overrides`` key). On any validation/guard failure nothing is written.
    """
    result = validate_update(
        fields, settings_obj=settings_obj,
        confirm_live=confirm_live, validator=validator,
    )
    env_overrides = result.pop("_env_overrides", None)
    if not result.get("ok"):
        return result

    if env_overrides:
        _write_env(env_path, env_overrides)

    return result


def _write_env(env_path: str | Path, env_overrides: dict[str, str]) -> None:
    """Persist key/values to ``.env`` preserving every other key.

    Uses python-dotenv ``set_key`` (lazy import). Creates the file if absent.
    """
    from dotenv import set_key  # lazy: dep-free import of this module

    p = Path(env_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch()
    for key, val in env_overrides.items():
        set_key(str(p), key, val, quote_mode="never")


__all__ = [
    "MASK",
    "FIELDS",
    "SECRET_ENVS",
    "ssid_is_demo",
    "read_settings",
    "validate_update",
    "apply_update",
]
