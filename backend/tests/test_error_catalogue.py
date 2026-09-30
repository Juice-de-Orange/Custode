"""`docs/errors.md` und der Code halten sich gegenseitig — in beide Richtungen.

**Warum das ein Gate braucht und keine Regel.** Der Katalog trug den Satz „Neue Codes werden hier
ergänzt **bevor** sie im Code verwendet werden" und brach ihn selbst: am 2026-08-03 fehlten
**59** von 93 verwendeten Slugs, neun Module hatten überhaupt keinen Abschnitt. Eine Regel, die
niemand ausführt, ist eine Absichtserklärung — und die DoD verlangt für jeden nutzerseitigen
Fehler einen Katalogeintrag.

Beide Richtungen zählen, und die zweite ist die unauffälligere:

* **Code → Katalog:** ein undokumentierter Slug ist ein Fehler, dessen Bedeutung nur im Quelltext
  steht. Der Web-Client verzweigt auf genau diese Zeichenketten.
* **Katalog → Code:** ein dokumentierter Slug, den niemand erzeugt, ist schlimmer als eine Lücke.
  Er sieht aus wie Abdeckung. Genau so standen `ssrf_blocked`, `payload_too_large` und
  `idempotency_replay` im Katalog, während der Code `import_url_blocked`, `file_too_large` und
  gar nichts warf — drei Fehlerbilder, die man vergeblich gesucht hätte.

Rein statisch (AST über ``app/`` + Markdown-Parsing), kein Docker.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.kernel.http.problem import _STATUS_SLUGS

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
CATALOGUE = BACKEND_DIR.parent / "docs" / "errors.md"

#: Slugs, die nicht als Literal im Code stehen, weil sie zur Laufzeit entstehen. Jeder Eintrag
#: nennt seine Quelle — sonst wäre diese Liste die Hintertür, durch die das Gate umgangen wird.
_DYNAMIC_SLUGS: dict[str, str] = {
    "only_children": (
        "accounts/service.py: `slug=reason` aus `exit_blocker_reason()` — der Austritt "
        "unterscheidet `last_admin` und `only_children` an derselben Stelle."
    ),
}

#: Stellen, an denen `slug=` **kein** Literal ist. Eine neue solche Stelle muss hier eingetragen
#: werden, sonst wird das Gate rot: sonst entstünde wieder ein Slug, den niemand katalogisiert.
_ALLOWED_DYNAMIC_SITES = {"app/modules/accounts/service.py"}

_SLUG_IN_TABLE = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`", re.MULTILINE)


def _literal_slugs() -> set[str]:
    """Jeder ``ProblemException(slug="…")``-Literalwert unter ``app/``."""
    return _scan()[0]


#: Die Fabrik des Kernels. Sie ist die einzige Stelle, an der ein `slug=` **nicht** einen neuen
#: Fehler benennt, sondern einen bereits benannten weiterreicht — ihre dynamischen Werte kommen aus
#: `_STATUS_SLUGS` und werden über :func:`_handler_slugs` erfasst.
_SLUG_PASSTHROUGH = {"_problem"}


def _scan() -> tuple[set[str], set[str]]:
    """(literale Slugs, Dateien mit nicht-literalem ``slug=``).

    Erfasst wird **jeder** Aufruf mit einem ``slug=``-Argument, nicht nur ``ProblemException(...)``.
    Die erste Fassung sah nur den Klassennamen — und übersah damit ``TokenReuseError``, das seinen
    Slug per ``super().__init__(slug="token_reuse")`` setzt. Das Gate fand die Lücke in sich selbst
    beim ersten Lauf: `token_reuse` stand im Katalog und galt als Geist. **Ein Muster, das an einem
    Namen hängt, prüft den Aufruf und nicht die Sache.**
    """
    slugs: set[str] = set()
    dynamic_sites: set[str] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _SLUG_PASSTHROUGH:
                continue
            for kw in node.keywords:
                if kw.arg != "slug":
                    continue
                if isinstance(kw.value, ast.Constant):
                    slugs.add(str(kw.value.value))
                else:
                    dynamic_sites.add(str(path.relative_to(BACKEND_DIR)))
    return slugs, dynamic_sites


def _handler_slugs() -> set[str]:
    """Die Slugs, die ``install_problem_handlers`` selbst erzeugt — ohne je ein
    ``ProblemException`` zu sehen. Sie sind genauso nutzersichtbar."""
    return {*_STATUS_SLUGS.values(), "error", "validation", "internal"}


def _emitted_slugs() -> set[str]:
    return _literal_slugs() | _handler_slugs() | set(_DYNAMIC_SLUGS)


def _documented_slugs() -> set[str]:
    """Slugs aus der ersten Spalte jeder Katalog-Tabelle."""
    return set(_SLUG_IN_TABLE.findall(CATALOGUE.read_text()))


def test_every_slug_the_code_can_emit_is_documented() -> None:
    """Der Gate. Fällt geschlossen aus: Schweigen ist keine Antwort."""
    missing = sorted(_emitted_slugs() - _documented_slugs())
    assert missing == [], (
        "Diese Slugs kann der Code erzeugen, aber docs/errors.md kennt sie nicht. Der Katalog "
        "ist der Vertrag, auf den die Web-Fehlertexte verzweigen — ein undokumentierter Slug ist "
        "ein Fehlerbild ohne Bedeutung."
    )


def test_no_documented_slug_is_a_ghost() -> None:
    """Die Rückrichtung, und die unauffälligere: ein Eintrag ohne Erzeuger sieht aus wie
    Abdeckung. So standen `ssrf_blocked`, `payload_too_large` und `idempotency_replay` monatelang
    im Katalog, während der Code drei andere Namen warf."""
    ghosts = sorted(_documented_slugs() - _emitted_slugs())
    assert ghosts == [], (
        "Diese Slugs stehen im Katalog, aber kein Codepfad erzeugt sie. Entweder den Erzeuger "
        "bauen oder den Eintrag entfernen — ein dokumentierter Fehler, den es nicht gibt, "
        "kostet beim Suchen mehr als eine Lücke."
    )


def test_dynamic_slug_sites_are_declared() -> None:
    """Ein ``slug=`` ohne Literal entzieht sich dem Gate. Eine neue solche Stelle muss ausdrücklich
    quittiert werden — sonst wäre der Weg zurück zu einem unkatalogisierten Slug wieder offen."""
    _, sites = _scan()
    undeclared = sorted(sites - _ALLOWED_DYNAMIC_SITES)
    assert undeclared == [], (
        "Nicht-literales `slug=` in diesen Dateien. Trage den Slug in _DYNAMIC_SLUGS ein "
        "(mit Quelle) und die Datei in _ALLOWED_DYNAMIC_SITES."
    )


def test_every_dynamic_entry_carries_its_source() -> None:
    weak = [slug for slug, why in _DYNAMIC_SLUGS.items() if len(why.strip()) < 30]
    assert weak == []


def test_the_catalogue_no_longer_declares_itself_incomplete() -> None:
    """Der Katalog trug einen Vorbehalt („Rund 59 Slugs fehlen hier"). Er ist eingelöst; der
    Vorbehalt darf nicht als Freibrief stehenbleiben, während das Gate darüber wacht."""
    text = CATALOGUE.read_text()
    assert "Dieser Katalog ist unvollständig" not in text
