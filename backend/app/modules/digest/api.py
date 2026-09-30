"""Public surface for ``digest``: the weekly fan-out the worker cron invokes. No HTTP, no table —
``digest`` reads ``accounts``/``tasks`` only through their public apis and is imported by no other
feature module (only the worker composition root calls it)."""

from __future__ import annotations

from app.modules.digest.service import send_weekly_digests

__all__ = ["send_weekly_digests"]
