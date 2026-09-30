"""Exported service interface for ``marketplace``.

Die Abhängigkeit ist einseitig (marketplace -> tasks.api/economy.api); bis 11-S1a war diese Fläche
deshalb leer. Der Austritt eines Mitglieds ist der erste Anlass von außen: er muss die offenen
Handelspositionen einer Person auflösen, **bevor** ihr Restsaldo verfällt — sonst kommt das
freigegebene Escrow nach dem Verfall an und liegt auf einem Konto, das niemandem mehr gehört.
Orchestriert wird das am Composition Root (``app/member_exit.py``), nicht hier.
"""

from app.modules.marketplace.service import release_positions_of

__all__ = ["release_positions_of"]
