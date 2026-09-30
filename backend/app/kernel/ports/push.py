"""Push als **Wecksignal**, nicht als Datentransport (ADR-012).

Die frühere Signatur nahm ``title`` und ``body`` entgegen — und widersprach damit genau der
Entscheidung, die sie umsetzen sollte: „FCM nur als Wecksignal **ohne Inhalte**". Ein Push mit
Titel und Text liefe über Googles Zustellung, und der Inhalt eines Haushalts hat dort nichts zu
suchen. Korrigiert am 2026-07-31, bevor Phase 10 darauf aufbaut (bis dahin gibt es keinen
Aufrufer und keinen Adapter — die Korrektur kostet jetzt nichts, später hätte sie einen Client
mitgezogen).

Der Vertrag ist deshalb: **wir wecken das Gerät, das Gerät holt sich den Rest über die
authentifizierte API.** ``topic`` sagt nur, *worum* es geht (z. B. ``"shopping"``), damit der
Client gezielt nachladen kann — nie *was* passiert ist. Die Anzeige einer Benachrichtigung baut der
Client aus den nachgeladenen Daten, nicht aus dem Push.
"""

from __future__ import annotations

from typing import Protocol


class PushPort(Protocol):
    async def wake(self, *, user_id: str, topic: str) -> bool:
        """Ein inhaltsloses Wecksignal an die Geräte einer Person. ``topic`` ist eine
        Invalidierungs-Kategorie, kein Text für Menschen. Antwort: wurde mindestens ein Gerät
        erreicht — der Aufrufer behandelt ``False`` als Normalfall, nicht als Fehler (Graceful
        Enhancement: ohne Push holt der Client beim nächsten Öffnen nach)."""
        ...
