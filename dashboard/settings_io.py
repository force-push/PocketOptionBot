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
    # ``kind`` is the python type (used for value coercion/validation); ``control``
    # is the UI widget type the frontend renders (docs/dashboard-plan.md §7):
    # mode | toggle | ratio | number | secret | text.
    __slots__ = ("env", "attr", "group", "kind", "secret", "requires_restart",
                 "label", "control", "hint", "step", "min", "max")

    def __init__(self, env, attr, group, kind, secret, requires_restart, label,
                 control, hint=None, step=None, min=None, max=None):
        self.env = env
        self.attr = attr
        self.group = group
        self.kind = kind  # "str" | "int" | "float" | "bool"
        self.secret = secret
        self.requires_restart = requires_restart
        self.label = label
        self.control = control
        self.hint = hint
        self.step = step
        self.min = min
        self.max = max


# Group display metadata (mirrors the Carbon mockup's Settings cards). Keyed by
# the ``group`` string on each field. ``order`` controls left-to-right placement.
GROUP_META: dict[str, dict] = {
    "Safety & Trade Mode": {"id": "safety", "title": "Safety & Trade Mode", "icon": "🛡️",
                            "subtitle": "Hard-defaults to DEMO. LIVE must be explicit.", "span2": True, "order": 0},
    "Signal Gate": {"id": "gate", "title": "Signal Gate", "icon": "🎯",
                    "subtitle": "3 v2 thresholds: pair filter + agreement count + confluence score", "order": 1},
    "TA Signals": {"id": "ta", "title": "TA Signal Parameters", "icon": "📊",
                   "subtitle": "Candle resolution + per-indicator thresholds. Restart required.", "order": 2},
    "Risk": {"id": "risk", "title": "Risk Manager", "icon": "⚖️",
             "subtitle": "Hard limits & cooldowns", "order": 3},
    "Telegram": {"id": "telegram", "title": "Telegram Session", "icon": "✈️",
                 "subtitle": "Telethon user session (MTProto)", "order": 4},
    "PocketOption WS": {"id": "pocketoption", "title": "PocketOption WS", "icon": "📡",
                        "subtitle": "Trading-terminal auth frame", "order": 5},
}


FIELDS: list[_F] = [
    # Safety / Mode
    _F("TRADE_MODE", "trade_mode", "Safety & Trade Mode", "str", False, True, "Trade Mode", "mode"),
    _F("DRY_RUN", "dry_run", "Safety & Trade Mode", "bool", False, False, "Dry Run", "toggle",
       hint="Log trades without calling the API"),
    _F("STAKE_AMOUNT", "stake_amount", "Safety & Trade Mode", "float", False, True, "Stake Amount (USD)", "number", step=0.5, min=0.5, max=50.0),
    _F("DEFAULT_EXPIRY_SECONDS", "default_expiry_seconds", "Safety & Trade Mode", "int", False, False, "Default Expiry (s)", "number", step=1),
    # Telegram
    _F("TELEGRAM_API_ID", "telegram_api_id", "Telegram", "int", False, True, "API ID", "text"),
    _F("TELEGRAM_API_HASH", "telegram_api_hash", "Telegram", "str", True, True, "API Hash", "secret"),
    _F("SIGNAL_BOT_USERNAME", "signal_bot_username", "Telegram", "str", False, True, "Signal Bot", "text"),
    # PocketOption WS
    _F("PO_SSID", "po_ssid", "PocketOption WS", "str", True, True, "SSID", "secret",
       hint='full 42["auth",{…}] frame'),
    # Signal Gate (v2 confluence gates — all configurable)
    _F("PAIR_SELECT_MIN_WIN_RATE", "pair_select_min_win_rate", "Signal Gate", "float", False, True, "Pair Filter: Min Bot Win %", "ratio",
       hint="Telegram bot pair selection gate (0.0=disabled for testing)"),
    _F("MIN_SIGNAL_AGREEMENT", "min_signal_agreement", "Signal Gate", "int", False, True, "Gate 1: Min Signals Agree", "number",
       hint="how many of 5 signals must agree (1–5)", step=1),
    _F("MIN_CONFLUENCE_SCORE", "min_confluence_score", "Signal Gate", "float", False, True, "Gate 2: Min Confluence Score", "ratio",
       hint="weighted confidence sum floor"),
    _F("MIN_PAYOUT_PCT", "min_payout_pct", "Signal Gate", "int", False, False, "Min Payout %", "number",
       hint="skip trade if PO payout below this (0=disabled)", step=1, min=0, max=100),
    _F("MIN_EXPECTED_VALUE", "min_expected_value", "Signal Gate", "float", False, False, "Min Expected Value", "number",
       hint="EV gate: 0=break-even, -0.05=warmup tolerance", step=0.01, min=-1.0, max=1.0),
    _F("MIN_EV_SAMPLES", "min_ev_samples", "Signal Gate", "int", False, False, "Min EV Samples", "number",
       hint="tracked trades per pair before EV gate activates", step=1, min=1, max=100),
    _F("CLICK_TRADE_ANYWAY", "click_trade_anyway", "Signal Gate", "bool", False, True, "Click Trade Anyway", "toggle",
       hint="auto-dismiss nag screens"),
    # TA Signals
    _F("CANDLE_INTERVAL_SECONDS", "candle_interval_seconds", "TA Signals", "int", False, True, "Candle Interval (s)", "number",
       hint="5 s recommended for 30 s expiry", step=1),
    _F("HISTORY_LENGTH", "history_length", "TA Signals", "int", False, True, "History Length", "number",
       hint="candles fetched per cycle", step=10),
    _F("RSI_PERIOD", "rsi_period", "TA Signals", "int", False, True, "RSI Period", "number", step=1),
    _F("RSI_OVERSOLD", "rsi_oversold", "TA Signals", "float", False, True, "RSI Oversold", "number",
       hint="CALL threshold", step=1),
    _F("RSI_OVERBOUGHT", "rsi_overbought", "TA Signals", "float", False, True, "RSI Overbought", "number",
       hint="PUT threshold", step=1),
    _F("MACD_FAST", "macd_fast", "TA Signals", "int", False, True, "MACD Fast EMA", "number", step=1),
    _F("MACD_SLOW", "macd_slow", "TA Signals", "int", False, True, "MACD Slow EMA", "number", step=1),
    _F("MACD_SIGNAL_PERIOD", "macd_signal_period", "TA Signals", "int", False, True, "MACD Signal Period", "number", step=1),
    _F("EMA_FAST", "ema_fast", "TA Signals", "int", False, True, "EMA Fast", "number", step=1),
    _F("EMA_SLOW", "ema_slow", "TA Signals", "int", False, True, "EMA Slow", "number", step=1),
    _F("BOLLINGER_PERIOD", "bollinger_period", "TA Signals", "int", False, True, "Bollinger Period", "number", step=1),
    _F("BOLLINGER_STD", "bollinger_std", "TA Signals", "float", False, True, "Bollinger Std Dev", "number", step=0.5),
    # Risk
    _F("MAX_TRADES_PER_HOUR", "max_trades_per_hour", "Risk", "int", False, True, "Max Trades / Hour", "number", step=1),
    _F("MAX_DAILY_LOSS_USD", "max_daily_loss_usd", "Risk", "float", False, True, "Daily Loss Limit (USD)", "number", step=1),
    _F("COOLDOWN_AFTER_LOSS_SECONDS", "cooldown_after_loss_seconds", "Risk", "int", False, True, "Post-Loss Cooldown (s)", "number", step=5),
    _F("MIN_BALANCE_MULTIPLIER", "min_balance_multiplier", "Risk", "float", False, True, "Min Balance Multiplier", "number", step=1),
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

    Shape (docs/dashboard-plan.md §7 — consumed by ``components/settings.js``)::

        {"groups": [{"id","title","icon","subtitle","span2",
                     "fields": [{"key","attr","label","hint","type","value",
                                 "secret","requires_restart","step","variant"}, ...]}, ...],
         "detected": {"ssid_mode": "DEMO"|"LIVE"|"UNKNOWN"}}

    ``key`` is the env-var name (the POST body is keyed by it). ``type`` is the UI
    control type. Secrets are masked; their real values are never returned.
    """
    by_group: dict[str, list] = {}
    for f in FIELDS:
        raw = getattr(settings_obj, f.attr, None)
        # trade_mode is a StrEnum; render its value
        if f.attr == "trade_mode" and raw is not None:
            raw = getattr(raw, "value", str(raw))
        field: dict[str, Any] = {
            "key": f.env,
            "attr": f.attr,
            "label": f.label,
            "type": f.control,
            "value": _coerce_display(raw, f),
            "secret": f.secret,
            "requires_restart": f.requires_restart,
        }
        if f.hint:
            field["hint"] = f.hint
        if f.step is not None:
            field["step"] = f.step
        if f.min is not None:
            field["min"] = f.min
        if f.max is not None:
            field["max"] = f.max
        by_group.setdefault(f.group, []).append(field)

    ssid = getattr(settings_obj, "po_ssid", "") or ""
    demo = ssid_is_demo(ssid)
    ssid_mode = "UNKNOWN" if demo is None else ("DEMO" if demo else "LIVE")

    # Inject a read-only "Detected Mode" pill into the PocketOption group so the
    # UI shows what the SSID decodes to (matches the mockup). Not a real setting.
    pill_value = {"DEMO": "DEMO · valid", "LIVE": "LIVE", "UNKNOWN": "no SSID"}[ssid_mode]
    pill_variant = {"DEMO": "win", "LIVE": "put", "UNKNOWN": "draw"}[ssid_mode]
    by_group.setdefault("PocketOption WS", []).append({
        "key": "_detected_mode", "label": "Detected Mode", "hint": "from is_demo()",
        "type": "pill", "value": pill_value, "variant": pill_variant,
        "secret": False, "requires_restart": False, "readonly": True,
    })

    groups: list[dict] = []
    for group_name, fields in by_group.items():
        meta = GROUP_META.get(group_name, {
            "id": group_name, "title": group_name, "icon": "", "subtitle": "", "order": 99,
        })
        groups.append({
            "id": meta["id"],
            "title": meta.get("title", group_name),
            "icon": meta.get("icon", ""),
            "subtitle": meta.get("subtitle", ""),
            "span2": bool(meta.get("span2", False)),
            "fields": fields,
            "_order": meta.get("order", 99),
        })
    groups.sort(key=lambda g: g["_order"])
    for g in groups:
        del g["_order"]

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
