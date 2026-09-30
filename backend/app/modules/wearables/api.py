"""Exported service interface — the only allowed synchronous entry into ``wearables`` from
outside the module (other modules and the worker import THIS, never internals).

Two kinds of export, deliberately kept apart:

* **The data seam** ``recovery_signal`` (9-S7, Synergie S-14). Member-scoped by signature AND by
  RLS: it takes a ``member_id``, and asking for anybody else's returns the neutral answer because
  the policy (migration 0069) yields no rows. It answers one boolean question — "is this person
  currently run down?" — never a score, because a raw health value crossing a module boundary is
  the health data itself. Consumers may shape what they OFFER that member with it and must never
  make it visible to anyone else (N-2, KONZEPT §9).
* **The background entry points** ``ingest_all`` / ``reap_wearable_daily`` (9-S6), which the
  worker composition root calls with the ports it composed.
"""

from app.modules.wearables.signal import NO_SIGNAL, RecoverySignal, recovery_signal
from app.modules.wearables.sync import IngestStats, ingest_all, reap_wearable_daily

__all__ = [
    "NO_SIGNAL",
    "IngestStats",
    "RecoverySignal",
    "ingest_all",
    "reap_wearable_daily",
    "recovery_signal",
]
