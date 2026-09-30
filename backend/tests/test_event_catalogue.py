"""Jeder emittierte Ereignistyp ist eingeordnet — und jede Einordnung wird emittiert.

**Warum das ein Gate braucht.** `invalidation_bridge` schlägt den Typ in `_ENTITY_BY_TYPE` nach
und kehrt bei einem Treffer-Miss **wortlos** zurück (`kernel/events/handlers.py`). Ein neues
Ereignis ohne Eintrag ist damit kein Fehler, sondern ein Nichts: die Fachänderung ist durabel, die
Oberfläche erfährt nie davon, und niemand sieht einen Unterschied zwischen „bewusst kein Hinweis"
und „vergessen". Genau so ist `market.trade.reverted` aus KONZEPT §5.10 nie entstanden — die
Stelle emittierte ein inhaltsloses `market.changed`, und der Name aus dem Konzept existierte
nirgends.

Das ist dieselbe Konstruktion wie beim Export und beim Haushalts-Purge: **wenn Schweigen eine
stillschweigende Antwort wäre, gehört die Frage in ein Gate.** Deshalb hier beide Richtungen —
unbekannter Typ ist ein Fehler, und ein Eintrag ohne Emission ist ein stiller No-Op, der beim
nächsten Umbenennen niemandem auffällt.

Der Test ist rein statisch (AST über `app/`) und braucht kein Docker.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.kernel.events.handlers import _ENTITY_BY_TYPE

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Emittiert, aber bewusst **ohne** SSE-Hinweis. Jede Zeile braucht einen Grund; „steht halt hier"
# ist keiner. Ein Eintrag hier heisst: die Oberfläche muss davon nichts erfahren.
_NO_SSE_HINT: dict[str, str] = {
    "household.dissolved": (
        "Der Haushalt ist beendet — jede Sitzung ist widerrufen, es gibt keinen Client mehr, der "
        "einen Hinweis empfangen koennte. Fachlich behandelt ihn `app/household_dissolution.py`."
    ),
    "shopping.item.checked": (
        "Uebergangs-Ereignis der Aktionsketten (KONZEPT §5.17). Der sichtbare Teil der Aenderung "
        "reist bereits als `shopping.changed`; ein zweiter Hinweis auf dieselbe Liste waere ein "
        "doppelter Refetch. Konsument ist der capture-Handler."
    ),
}


def _emitted_event_types() -> set[str]:
    """Alle literalen ``type=``-Werte aller ``emit(...)``-Aufrufe unter ``app/``.

    Literal heisst literal: die zwei dynamischen Emissionen im Sync-Pfad
    (``f"{spec.module}.changed"`` und die ``transition_events`` der Spec) sind hier nicht
    greifbar und werden unten aus der Spec selbst nachgezogen — abgeleitet, nicht gepflegt.
    """
    found: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "emit":
                continue
            for kw in node.keywords:
                if kw.arg == "type" and isinstance(kw.value, ast.Constant):
                    found.add(str(kw.value.value))
    return found


def _sync_event_types() -> set[str]:
    """Die Ereignisse, die der generische Sync-Pfad zur Laufzeit baut — aus der Spec abgeleitet."""
    from app.modules.shopping.spec import SHOPPING_SPEC

    types = {f"{SHOPPING_SPEC.module}.changed"}
    for entity in SHOPPING_SPEC.entities.values():
        types.update(entity.transition_events.values())
    return types


def _all_event_types() -> set[str]:
    return _emitted_event_types() | _sync_event_types()


def test_every_emitted_event_is_classified() -> None:
    """Der eigentliche Gate, und er faellt geschlossen aus.

    Ein neuer Ereignistyp gehoert entweder in `_ENTITY_BY_TYPE` (die Oberflaeche soll nachladen)
    oder mit Begruendung in `_NO_SSE_HINT`. Schweigen ist keine Antwort — es sieht im Betrieb
    exakt so aus wie „funktioniert".
    """
    unclassified = sorted(_all_event_types() - set(_ENTITY_BY_TYPE) - set(_NO_SSE_HINT))
    assert unclassified == [], (
        "Diese Ereignisse werden emittiert, aber nirgends eingeordnet. Entweder eine Zeile in "
        "kernel/events/handlers.py::_ENTITY_BY_TYPE, oder ein Eintrag in _NO_SSE_HINT mit Grund."
    )


def test_no_mapping_is_a_ghost() -> None:
    """Die Rueckrichtung. Ein Eintrag fuer ein Ereignis, das niemand mehr emittiert, ist ein
    stiller No-Op — und beim naechsten Umbenennen glaubt jeder, der Hinweis liefe noch."""
    ghosts = sorted(set(_ENTITY_BY_TYPE) - _all_event_types())
    assert ghosts == [], "Eintraege ohne Emission — tote Zeilen, die wie Abdeckung aussehen"


def test_every_exemption_carries_a_real_reason() -> None:
    """`_NO_SSE_HINT` ist eine Freigabe, keine Ablage. Ohne Begruendung waere sie nur ein
    bequemerer Weg, das Gate zu umgehen."""
    weak = [key for key, reason in _NO_SSE_HINT.items() if len(reason.strip()) < 40]
    assert weak == []


def test_no_type_is_both_mapped_and_exempt() -> None:
    """Stuende ein Typ in beiden, gewaenne stillschweigend die Map — und die Freigabe saehe aus
    wie eine Entscheidung, die nichts bewirkt."""
    overlap = sorted(set(_ENTITY_BY_TYPE) & set(_NO_SSE_HINT))
    assert overlap == []


def test_the_konzept_events_of_the_marketplace_exist() -> None:
    """KONZEPT §5.10 nennt vier Ereignisse namentlich. Drei gab es; `market.trade.reverted` war
    bis 11-B4 nur ein Name im Konzept — die Stelle emittierte `market.changed`, denselben Typ wie
    der Rueckzug. Zwei Vorgaenge unter einem Namen sind kein Ereignis, sondern ein Signal."""
    emitted = _all_event_types()
    for event_type in (
        "market.listing.created",
        "market.listing.sold",
        "market.trade.settled",
        "market.trade.reverted",
    ):
        assert event_type in emitted, f"KONZEPT §5.10 verlangt {event_type}"
