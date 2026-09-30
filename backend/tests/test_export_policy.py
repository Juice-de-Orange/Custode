"""Gates on the export policy. No database — these compare declared intent against the schema.

Two failure modes are worth failing CI over, because neither is visible in review:

1. A new table appears and nobody decides whether it belongs in a person's export. Silence would
   mean "absent", and an export that quietly omits data is worse than none — it claims to be
   complete.
2. A new secret-bearing column appears in an already-exported table and nobody redacts it. Silence
   would mean "exported", and the secret leaves the server in a file the subject may e-mail on.

Both gates therefore fail closed: unclassified is an error, not a default.
"""

from __future__ import annotations

import re

import pytest

import app.main  # noqa: F401  — imports every model into Base.metadata
from app.export_policy import ATTACHMENT_COLUMNS, EXCLUDED, EXPORTED, POLICY
from app.kernel.db.base import Base
from app.kernel.export import REDACTED, ExportPolicy, TableSpec

_EXPORTED_NAMES = {spec.name for spec in EXPORTED}

# Names that *look* like they carry a secret. Deliberately wider than the real set: the point is to
# catch the next one, so a false positive here costs one line of classification and a false
# negative costs a leak.
_SENSITIVE_NAME = re.compile(r"hash|secret|token|password|_enc$|wrapped|(^|_)code$|(^|_)key$")

# Columns whose name trips the pattern above but which are safe — each with the reason it is safe.
# Anything not listed here and not redacted fails the gate.
_REVIEWED_SAFE: dict[str, str] = {
    "auth_passkeys.public_key": "öffentlicher Teil eines Passkeys — per Definition nicht geheim",
    "recipes.photo_key": "Blob-Referenz, kein Geheimnis (Zugriff läuft über signierte URLs)",
    "guide_attachments.storage_key": "Blob-Referenz, kein Geheimnis",
    "vault_items.ciphertext": "IST das Nutzerdatum — ohne den Schlüssel wertlos, der redigiert ist",
    "wearable_connections.token_expires_at": "Zeitstempel, kein Token",
    "auth_login_events.country_code": "Ländercode, kein Geheimnis (die IP wird nie gespeichert)",
}


def test_every_orm_table_is_classified() -> None:
    """A table is either exported or excluded with a reason — never merely forgotten.

    This is the fast half: it sees only what the ORM declares. The half that matters runs against
    the real database (``tests/test_export_schema_gate.py``) — the ORM is a *subset* of the schema,
    and the gap is where `tenancy_probe` hid.
    """
    known = _EXPORTED_NAMES | set(EXCLUDED)
    unclassified = sorted(set(Base.metadata.tables) - known)
    assert not unclassified, (
        "Neue Tabelle(n) ohne Export-Entscheidung: "
        + ", ".join(unclassified)
        + ". In app/export_policy.py entweder zu EXPORTED (mit personal_columns, falls die "
        "Zeile einer Person zuzuordnen ist) oder zu EXCLUDED mit Begründung aufnehmen."
    )


def test_exported_tables_all_exist_in_the_orm() -> None:
    """Was exportiert wird, muss die Anwendung auch kennen — sonst liefe der Export gegen eine
    Tabelle, für die es kein Modell gibt.

    Für die AUSGESCHLOSSENEN gilt das bewusst nicht: `tenancy_probe` existiert nur in einer
    Migration, ist aber für `custode_app` lesbar und musste deshalb eine Entscheidung bekommen.
    Dass die Ausschlussliste keine Karteileichen enthält, prüft das Schema-Gate gegen die echte
    Datenbank."""
    ghosts = sorted(_EXPORTED_NAMES - set(Base.metadata.tables))
    assert not ghosts, f"Export-Policy exportiert nicht existierende Tabellen: {ghosts}"


def test_no_table_is_both_exported_and_excluded() -> None:
    assert not (_EXPORTED_NAMES & set(EXCLUDED))


def test_every_exclusion_carries_a_reason() -> None:
    """A bare table name in EXCLUDED would be an assertion nobody can check later."""
    thin = sorted(name for name, reason in EXCLUDED.items() if len(reason.strip()) < 20)
    assert not thin, f"Ausschluss ohne tragfähige Begründung: {thin}"


def test_every_secret_looking_column_is_redacted_or_reviewed() -> None:
    """The gate that stops a leak: a secret-bearing column in an exported table must be redacted."""
    findings: list[str] = []
    for spec in EXPORTED:
        table = Base.metadata.tables[spec.name]
        redacted = POLICY.redact.get(spec.name, frozenset())
        for column in table.columns:
            if not _SENSITIVE_NAME.search(column.name):
                continue
            if column.name in redacted:
                continue
            if f"{spec.name}.{column.name}" in _REVIEWED_SAFE:
                continue
            findings.append(f"{spec.name}.{column.name}")
    assert not findings, (
        "Spalte(n) mit geheimnisverdächtigem Namen werden exportiert: "
        + ", ".join(sorted(findings))
        + ". Entweder in app/export_policy.py._REDACT aufnehmen oder in "
        "tests/test_export_policy.py._REVIEWED_SAFE mit Begründung freigeben."
    )


def test_redaction_targets_exist() -> None:
    """Redacting a column that no longer exists is a silent no-op — the next rename would ship the
    value. Pin the names to the schema."""
    for table_name, columns in POLICY.redact.items():
        assert table_name in Base.metadata.tables, f"redigierte Tabelle fehlt: {table_name}"
        actual = {c.name for c in Base.metadata.tables[table_name].columns}
        missing = sorted(columns - actual)
        assert not missing, f"{table_name}: redigierte Spalte(n) existieren nicht: {missing}"


def test_reviewed_safe_entries_still_exist() -> None:
    """Same for the allow-list — a stale entry would hide a genuinely new finding."""
    for ref in _REVIEWED_SAFE:
        table_name, column = ref.split(".", 1)
        assert table_name in Base.metadata.tables, f"unbekannte Tabelle in _REVIEWED_SAFE: {ref}"
        actual = {c.name for c in Base.metadata.tables[table_name].columns}
        assert column in actual, f"unbekannte Spalte in _REVIEWED_SAFE: {ref}"


def test_personal_columns_exist_on_their_table() -> None:
    """A typo here would silently produce an empty personal export instead of an error."""
    for spec in EXPORTED:
        actual = {c.name for c in Base.metadata.tables[spec.name].columns}
        missing = sorted(set(spec.personal_columns) - actual)
        assert not missing, f"{spec.name}: personal_columns existieren nicht: {missing}"


def test_policy_rejects_unsafe_identifiers() -> None:
    """Table names are interpolated into SQL, so the value object refuses anything that is not a
    plain identifier — a bug must not become an injection."""
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        ExportPolicy(tables=(TableSpec("recipes; DROP TABLE users", shared=True),))
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        ExportPolicy(
            tables=(TableSpec("recipes", shared=True),), redact={"recipes": frozenset({"a b"})}
        )


def test_redacted_marker_is_visible_not_empty() -> None:
    """A withheld value shows as a marker rather than a missing key: the export states that
    something exists and was kept back, instead of implying it does not exist."""
    assert REDACTED and REDACTED != ""


def test_blob_references_are_actually_collected_as_attachments() -> None:
    """A column waved through as "Blob-Referenz, kein Geheimnis" must also be *fetched*.

    Otherwise the two lists drift apart in the worst direction: the column counts as harmless
    because it is only a pointer, while nothing ever follows the pointer — and the export quietly
    ships recipe rows whose photos are missing without saying so.
    """
    waved_through = {
        ref for ref, reason in _REVIEWED_SAFE.items() if reason.startswith("Blob-Referenz")
    }
    collected = {f"{table}.{column}" for table, column in ATTACHMENT_COLUMNS.items()}
    assert waved_through == collected, (
        "Blob-Referenzen und ATTACHMENT_COLUMNS stimmen nicht überein: "
        f"nur freigegeben {sorted(waved_through - collected)}, "
        f"nur eingesammelt {sorted(collected - waved_through)}"
    )


def test_attachment_columns_belong_to_exported_tables() -> None:
    for table, column in ATTACHMENT_COLUMNS.items():
        assert table in _EXPORTED_NAMES, f"{table} liefert Anhänge, wird aber nicht exportiert"
        actual = {c.name for c in Base.metadata.tables[table].columns}
        assert column in actual, f"{table}.{column} existiert nicht"


def test_a_table_that_would_appear_in_no_export_is_refused() -> None:
    """Weder geteilt noch personenbezogen heisst: die Tabelle taucht nirgends auf. Das ist immer
    ein Klassifizierungsfehler und nie Absicht — also ein Fehler beim Bau der Policy, nicht eine
    stille Leerstelle im Archiv."""
    with pytest.raises(ValueError, match="in keinem Export"):
        ExportPolicy(tables=(TableSpec("recipes"),))


def test_shared_and_shared_when_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="schliessen sich aus"):
        ExportPolicy(
            tables=(
                TableSpec(
                    "calendar_events",
                    ("owner_id",),
                    shared=True,
                    shared_when=("layer", "household"),
                ),
            )
        )


def test_personal_tables_outnumber_nothing_silently() -> None:
    """Dokumentiert die Voreinstellung: `shared` muss AUSDRUECKLICH gesetzt werden. Wer eine neue
    Tabelle ohne Nachdenken aufnimmt, bekommt die restriktive Antwort — zu wenig Daten, nie die
    einer anderen Person."""
    assert TableSpec("x", ("y",)).shared is False
