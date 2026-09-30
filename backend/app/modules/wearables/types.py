"""Consent vocabulary and provider constants (P9-S5). Pure — no DB, no I/O, no adapter import.

KONZEPT §5.15 requires consent **per data type**, and the types it names are finer than the
scopes Oura hands out (``daily`` alone covers sleep, readiness and activity). Keeping our own
vocabulary means a user can consent to sleep but not to activity even though one provider scope
covers both: we request the union of scopes, then filter per type at ingest time (9-S6).

The ``wearable_`` prefix keeps these distinguishable inside the shared ``consents`` ledger,
which also carries ``child_account``.
"""

from __future__ import annotations

PROVIDER_OURA = "oura"

CONSENT_SLEEP = "wearable_sleep"
CONSENT_READINESS = "wearable_readiness"
CONSENT_ACTIVITY = "wearable_activity"
CONSENT_HEARTRATE = "wearable_heartrate"

#: Every consentable data type, in a stable order (responses and tests rely on it).
ALL_CONSENT_TYPES: tuple[str, ...] = (
    CONSENT_SLEEP,
    CONSENT_READINESS,
    CONSENT_ACTIVITY,
    CONSENT_HEARTRATE,
)

#: Consent type -> provider scopes needed to read it. The authorize step requests the UNION
#: over the chosen types, so consenting to sleep only never asks for the heart-rate scope.
_OURA_SCOPES: dict[str, tuple[str, ...]] = {
    CONSENT_SLEEP: ("daily",),
    CONSENT_READINESS: ("daily",),
    CONSENT_ACTIVITY: ("daily",),
    CONSENT_HEARTRATE: ("heartrate",),
}


def scopes_for(consent_types: list[str]) -> list[str]:
    """Provider scopes needed for the given consent types — sorted, deduplicated.

    Sorted because the resulting authorize URL is asserted in tests and compared by operators;
    an unstable scope order would make it look like the request changed when it did not."""
    scopes: set[str] = set()
    for consent_type in consent_types:
        scopes.update(_OURA_SCOPES.get(consent_type, ()))
    return sorted(scopes)
