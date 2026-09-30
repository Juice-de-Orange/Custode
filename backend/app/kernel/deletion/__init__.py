"""Endgültiges Ausräumen nach der Karenz (Art. 17) — für ein **Konto** und für einen **Haushalt**.

Mechanik ohne Tabellennamen — die Regeln kommen vom Composition Root
(``app/deletion_policy.py`` bzw. ``app/household_deletion_policy.py``), wie beim Retention-Reaper
und beim Export (ADR-0039).

Die beiden unterscheiden sich in einem Punkt, und der ist kein Detail: der **Konto**-Purge bekommt
seine Spaltenliste gepflegt, weil ein Personenbezug nicht am Schema abzulesen ist (``author_id``,
``cook_id``, ``contact_id`` …). Der **Haushalts**-Purge leitet seine Tabellenmenge dagegen zur
Laufzeit aus dem Katalog ab: ``household_id`` *ist* am Schema abzulesen, und kein Fremdschlüssel
zeigt auf ``households.id``, der eine vergessene Tabelle melden könnte (ADR-0086).
"""

from app.kernel.deletion.household import (
    HouseholdPurgeResult,
    HouseholdPurgeSpec,
    UnclassifiedTableError,
    delete_household_row,
    discover_household_tables,
    order_children_first,
    plan_purge,
    purge_tables,
)
from app.kernel.deletion.purge import PurgeResult, PurgeSpec, purge_user

__all__ = [
    "HouseholdPurgeResult",
    "HouseholdPurgeSpec",
    "PurgeResult",
    "PurgeSpec",
    "UnclassifiedTableError",
    "delete_household_row",
    "discover_household_tables",
    "order_children_first",
    "plan_purge",
    "purge_tables",
    "purge_user",
]
