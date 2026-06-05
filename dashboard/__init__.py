"""Trading dashboard backend (Work Package A).

Layout (see docs/dashboard-plan.md):
- analytics.py   : DEP-FREE parsing/aggregation of decisions.jsonl (stdlib only)
- settings_io.py : DEP-FREE except pydantic — masked read + guarded .env write
- state_bridge.py: fail-closed StateBridge the bot uses to emit live state
- models.py      : pydantic response/event models (FastAPI side)
- server.py      : FastAPI app + `python -m dashboard.server`

The first three modules import without fastapi/uvicorn/watchfiles so the core
logic stays unit-testable offline.
"""

__all__ = ["analytics", "settings_io", "state_bridge"]
