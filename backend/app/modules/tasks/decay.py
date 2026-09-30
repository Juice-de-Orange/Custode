"""Sanfter Wert-Verfall überfälliger Aufgaben (KONZEPT §5.9, Entscheidung 17.1).

Statt Strafen schmilzt der **Punktwert** einer überfälligen Aufgabe täglich: pro vollem Tag über
der Fälligkeit -10 %, Untergrenze 50 %. Wer trödelt, verdient weniger — die Währung bleibt knapp,
ohne dass jemand bestraft wird (kein Saldo-Abzug). Reine Funktion; angewandt beim Erledigen.

P4-S4: feste Defaults. Die per-Haushalt-Konfiguration (``households.settings_json``, abschaltbar)
folgt als kleiner Folge-Slice — die Konstanten hier sind dann die Defaults."""

from __future__ import annotations

from datetime import datetime

DECAY_PER_DAY = 0.10  # 10% weniger je vollem Tag über der Fälligkeit
FLOOR = 0.50  # nie unter 50 % des Basiswerts


def effective_points(base: int, due_at: datetime | None, now: datetime) -> int:
    """Effective award for completing a task now: ``base`` reduced by 10 % per whole day overdue,
    floored at 50 %. No deadline (``due_at`` is None) or not yet overdue → full ``base``."""
    if base <= 0 or due_at is None or now <= due_at:
        return base
    days_overdue = (now - due_at).days  # whole days (floor for a positive delta)
    if days_overdue <= 0:
        return base
    multiplier = max(FLOOR, 1.0 - DECAY_PER_DAY * days_overdue)
    return round(base * multiplier)
