"""Turn a collected export into the ZIP the subject downloads (Art. 20: "gängiges Format").

Layout — structural names in English so tooling can rely on them, the human text in German like
every other server-generated text in this codebase (the digest mails do the same; there is no
backend i18n runtime):

    manifest.json          machine-readable: scope, counts, what was withheld and why
    LIESMICH.txt           the same in prose, for someone who opens the ZIP and not the JSON
    data/<table>.json      one file per table — a 40-MB single document helps nobody
    attachments/<key>      the blobs the rows reference

Three properties matter more than the layout:

**The manifest is part of the answer, not decoration.** An export that silently omits data claims
a completeness it does not have. So everything absent is *named*: tables excluded by policy with
their reason, columns withheld with the marker, attachments that could not be read. A reader can
tell "this household has no recipes" from "recipes were not exported".

**Attachments degrade, they do not fail.** With no storage backend configured (Null adapter) the
JSON still describes every photo; the manifest says the files are absent and why. Losing the whole
export because one blob is missing would be the wrong trade.

**No path comes from a row.** Blob keys are server-generated, but they still reach us through a
database column, so the archive derives the entry name from a sanitised final segment — a ZIP that
writes ``../../etc`` on extraction is a real attack against the person who opens it.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .collect import ExportPolicy as _ExportPolicy
from .collect import ExportResult, ExportScope, redacted_columns

_ATTACHMENT_DIR = "attachments"
_DATA_DIR = "data"


@dataclass(frozen=True)
class Attachment:
    """One blob the export should carry, and where it came from."""

    key: str
    data: bytes | None
    table: str


def safe_entry_name(key: str) -> str:
    """The archive name for a blob key — final segment only, no traversal, never empty.

    Keys are server-generated today. This is defence against the *next* code path that writes one,
    because the cost of being wrong lands on whoever extracts the ZIP, not on us.
    """
    candidate = key.replace("\\", "/").split("/")[-1].strip()
    if not candidate or candidate in {".", ".."}:
        return "unbenannt"
    return "".join(c for c in candidate if c.isalnum() or c in "-_.") or "unbenannt"


def _readme(
    *,
    scope: ExportScope,
    generated_at: dt.datetime,
    result: ExportResult,
    withheld: Sequence[str],
    excluded: Mapping[str, str],
    attachments_included: int,
    attachments_missing: int,
) -> str:
    which = (
        "alle Daten deines Haushalts, soweit dein Konto sie sehen darf"
        if scope is ExportScope.HOUSEHOLD
        else "die Daten, die dir persönlich zuzuordnen sind"
    )
    lines = [
        "Datenexport",
        "===========",
        "",
        f"Erstellt am {generated_at.strftime('%d.%m.%Y um %H:%M Uhr')} (UTC).",
        f"Umfang: {which}.",
        "",
        f"In data/ liegt je Tabelle eine JSON-Datei, insgesamt {result.row_count} Zeilen.",
        f"In {_ATTACHMENT_DIR}/ liegen {attachments_included} Anhänge"
        + (
            f" ({attachments_missing} nicht lesbar, s. manifest.json)."
            if attachments_missing
            else "."
        ),
    ]
    if withheld:
        lines += [
            "",
            "Was NICHT enthalten ist",
            "-----------------------",
            'Einzelne Werte sind bewusst zurückgehalten und im JSON als "<redaktiert>" markiert.',
            "Der Schlüssel bleibt sichtbar, damit du siehst, DASS es den Wert gibt:",
        ]
        lines += [f"  - {ref}" for ref in withheld]
        lines += [
            "",
            "Es handelt sich um Passwort-/PIN-Prüfwerte, Sitzungs- und Feed-Geheimnisse,",
            "Zugangsdaten zu fremden Systemen (z. B. dein CalDAV-Passwort, dein Oura-Token)",
            "und den Schlüssel deines Tresors. Die Tresor-INHALTE sind enthalten — sie sind",
            "verschlüsselt und lassen sich nur in der App mit deiner Passphrase öffnen.",
        ]
    lines += [
        "",
        "Ganze Tabellen, die nicht in den Export gehören",
        "-----------------------------------------------",
        'Jeweils mit dem Grund. Das ist NICHT durchweg „kein Personenbezug" — das Betreiber-Audit',
        "etwa trägt sehr wohl Personenbezug, ist aber unser Sicherheitsprotokoll und für die",
        "Anwendung nicht einmal lesbar:",
    ]
    lines += [f"  - {name}: {reason}" for name, reason in sorted(excluded.items())]
    if result.narrowed:
        lines += [
            "",
            "Auf dich eingeengt",
            "------------------",
            "Diese Tabellen gehören nicht dem ganzen Haushalt. Du bekommst deine eigenen Zeilen;",
            "die der anderen Mitglieder gehören ihnen und stehen in DEREN Export:",
        ]
        lines += [f"  - {name}" for name in sorted(result.narrowed)]
    if result.skipped:
        lines += [
            "",
            "Nur im Haushalts-Export enthalten (gehört dem Haushalt, nicht einer Person)",
            "--------------------------------------------------------------------------",
        ]
        lines += [f"  - {name}" for name in sorted(result.skipped)]
    lines += [
        "",
        "Fragen dazu beantwortet der Betreiber über den Feedback-Kanal in der App.",
        "",
    ]
    return "\n".join(lines)


def build_export_archive(
    result: ExportResult,
    *,
    policy: _ExportPolicy,
    scope: ExportScope,
    generated_at: dt.datetime,
    attachments: Sequence[Attachment] = (),
    excluded_tables: Mapping[str, str] | None = None,
    storage_available: bool = True,
) -> bytes:
    """Build the ZIP. Pure apart from the clock, which the caller supplies."""
    excluded = dict(excluded_tables or {})
    # Nur die Spalten nennen, deren Tabelle in DIESEM Archiv auch eine Datei hat. Sonst stand
    # `invites.code` im persoenlichen Export unter „Der Schluessel bleibt sichtbar", waehrend
    # `data/invites.json` dort gar nicht existiert — und dieselbe Tabelle zwanzig Zeilen tiefer
    # korrekt unter „nur im Haushalts-Export". Ein Text, der sich selbst widerspricht, ist
    # schlimmer als einer, der schweigt.
    withheld = [ref for ref in redacted_columns(policy) if ref.split(".", 1)[0] in result.sections]

    included = [a for a in attachments if a.data is not None]
    missing = [a for a in attachments if a.data is None]

    manifest = {
        "format": "custode-export/1",
        "scope": scope.value,
        "generated_at": generated_at.isoformat(),
        "sections": {name: len(rows) for name, rows in sorted(result.sections.items())},
        "row_count": result.row_count,
        "withheld_columns": withheld,
        "withheld_marker": "<redaktiert>",
        "excluded_tables": excluded,
        "skipped_tables": dict(sorted(result.skipped.items())),
        # Der Unterschied, der zaehlt: "fehlt ganz" ist nicht dasselbe wie "auf dich eingeengt".
        # Ohne diese Liste behauptete ein Haushalts-Export Vollstaendigkeit, die er nicht hat.
        "narrowed_tables": dict(sorted(result.narrowed.items())),
        "attachments": {
            "included": [a.key for a in included],
            "unreadable": [a.key for a in missing],
            "storage_available": storage_available,
            "note": (
                "Anhänge fehlen vollständig: für dieses Deployment ist kein Blob-Speicher "
                "konfiguriert (Null-Adapter). Die Datensätze in data/ beschreiben sie trotzdem."
                if not storage_available
                else None
            ),
        },
    }

    buffer = io.BytesIO()
    # ZIP_DEFLATED: these are JSON documents, and the subject may be on a phone connection.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(
            "LIESMICH.txt",
            _readme(
                scope=scope,
                generated_at=generated_at,
                result=result,
                withheld=withheld,
                excluded=excluded,
                attachments_included=len(included),
                attachments_missing=len(missing),
            ),
        )
        for table, rows in sorted(result.sections.items()):
            archive.writestr(
                f"{_DATA_DIR}/{table}.json",
                json.dumps(rows, ensure_ascii=False, indent=2),
            )
        seen: set[str] = set()
        for attachment in included:
            name = safe_entry_name(attachment.key)
            # Two rows can reference the same blob; a ZIP with duplicate names is legal but
            # confuses extractors, so keep the first and let the manifest carry both keys.
            if name in seen:
                continue
            seen.add(name)
            archive.writestr(f"{_ATTACHMENT_DIR}/{name}", attachment.data or b"")
    return buffer.getvalue()
