"""Raum-Heatmap (KONZEPT §5.9/§5.8): die „Hitze" eines Raums = f(letzte Erledigung seiner Tasks,
``decay_days``). Reine Schwellenfunktion; die Aggregation (letzte Erledigung je Raum) liegt im
``service``. Status wird NIE gespeichert, immer berechnet."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

RoomStatus = Literal["green", "amber", "red"]


def room_status(last_done: datetime | None, decay_days: int, now: datetime) -> RoomStatus:
    """green = frisch (< 50 % des Fensters), amber = wird fällig (< 100 %), red = überfällig oder
    noch nie erledigt. ``decay_days`` ist das Verfall-Fenster des Raums (Tage)."""
    if last_done is None:
        return "red"
    age_days = (now - last_done).total_seconds() / 86400.0
    ratio = age_days / decay_days
    if ratio < 0.5:
        return "green"
    if ratio < 1.0:
        return "amber"
    return "red"
