"""Collect a subject-rights export from the database (Art. 15 Auskunft / Art. 20 Portabilität).

Two guarantees carry this module, and both are enforced rather than documented:

**Tenancy comes from RLS, not from a WHERE clause.** The export runs on the caller's own scoped
session, so it can only ever read what that caller may read. Nothing here filters by
``household_id``; a missing filter therefore cannot leak a foreign household. It also means the
member-scoped Art.-9 tables (``member_id`` in the policy predicate, ADR-0081) stay invisible to
an admin exporting the household — the database refuses, not this code.

**Redaction is a denylist that fails closed.** ``ExportPolicy.redact`` names the columns whose
values must never leave the server: authenticators, session credentials, third-party credentials
the *server* can use, and key material. A column that is not classified is a bug — the CI gate in
``tests/test_export_policy.py`` walks ``Base.metadata`` and fails on anything unclassified, so a
new sensitive column cannot slip into an export by being forgotten.

Table names cannot be bound as SQL parameters, so every identifier is validated against a strict
pattern before interpolation. Names are code-defined (never user input): a mismatch is a bug, not
an attack — same reasoning as ``kernel/retention/reaper.py``.
"""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The placeholder a redacted value is replaced with. A visible marker beats omitting the key:
# the export then *shows* that something exists and was withheld, instead of implying it does not.
REDACTED = "<redaktiert>"


class ExportTooLarge(Exception):
    """More rows than the direct download may hold. Raised **while collecting**, not afterwards.

    Checking the finished archive would be theatre: by then the rows, the JSON and the ZIP have all
    been held in memory at once, and the request that answers 413 has already cost several hundred
    megabytes. The limit has to bite before the memory is spent, or it protects nothing.
    """

    def __init__(self, rows: int, limit: int) -> None:
        super().__init__(f"export exceeds {limit} rows (stopped at {rows})")
        self.rows = rows
        self.limit = limit


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class ExportScope(enum.Enum):
    """Which rows an export run collects.

    ``HOUSEHOLD`` — everything the caller's session can see. For an admin that is the shared
    household record; RLS still withholds other members' member-scoped data.

    ``PERSONAL`` — only rows tied to the requesting person via one of the table's
    ``personal_columns``. A shared shopping list is not "data concerning" one member, so tables
    without such a column are skipped entirely rather than exported wholesale.
    """

    HOUSEHOLD = "household"
    PERSONAL = "personal"


@dataclass(frozen=True)
class TableSpec:
    """One table's place in an export.

    ``personal_columns`` names the columns that tie a row to a person (``author_id``,
    ``member_id``, ``user_id``, …). Empty means the table carries no personal attribution.

    ``shared`` is the one field with real consequences, and it **defaults to False on purpose**.
    It answers: may every member of the household see every row of this table? Only then does a
    household export read the table whole.

    Why the default is the restrictive one: this codebase draws a lot of owner boundaries in the
    *service layer* rather than in RLS. A calendar event on the ``personal`` layer is a 404 for a
    co-member (ADR-0040), a CalDAV subscription is owner-only, a letter goes to named recipients —
    and none of that is in a policy predicate. An export that trusted RLS alone would be the one
    path in the system that walks around all of it. So a table nobody classified yields *too
    little* data, never someone else's.

    ``personal_text_columns`` is for the one place where a person is not a uuid column: the points
    ledger addresses accounts as strings (``member:<uuid>``, ``system``, ``escrow:<id>``,
    ADR-0035). Comparing a uuid against ``varchar`` is a type error, so those columns are matched
    against ``personal_text_prefix + subject`` instead. Which movements are "about" a person is
    decided by the accounts they touch — not by who happened to book them.

    ``shared_when`` covers the tables that are shared only in part: ``("layer", "household")`` on
    calendar events means household-layer rows belong to everyone, personal-layer rows to their
    owner. Without it the two would have to be one or the other, and both answers are wrong.
    """

    name: str
    personal_columns: tuple[str, ...] = ()
    shared: bool = False
    shared_when: tuple[str, str] | None = None
    personal_text_columns: tuple[str, ...] = ()
    personal_text_prefix: str = ""


@dataclass(frozen=True)
class ExportPolicy:
    """What may be exported, and what must be withheld.

    ``tables`` is the allow-list; anything not listed is absent by construction. ``redact`` maps a
    table name to the columns whose values are replaced with :data:`REDACTED`.
    """

    tables: tuple[TableSpec, ...]
    redact: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for spec in self.tables:
            _check_ident(spec.name)
            for column in spec.personal_columns:
                _check_ident(column)
            if spec.shared_when is not None:
                _check_ident(spec.shared_when[0])
                if spec.shared:
                    raise ValueError(f"{spec.name}: shared und shared_when schliessen sich aus")
            for column in spec.personal_text_columns:
                _check_ident(column)
            if (
                not spec.shared
                and not spec.personal_columns
                and not spec.personal_text_columns
                and spec.shared_when is None
            ):
                # Would be absent from BOTH scopes — always a classification mistake, never intent.
                raise ValueError(
                    f"{spec.name}: weder shared noch personenbezogen — so erscheint die Tabelle "
                    "in keinem Export"
                )
        for table, columns in self.redact.items():
            _check_ident(table)
            for column in columns:
                _check_ident(column)


@dataclass(frozen=True)
class ExportResult:
    """Collected sections plus the manifest that says what the export does and does not contain."""

    sections: dict[str, list[dict[str, Any]]]
    skipped: dict[str, str]
    narrowed: dict[str, str] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return sum(len(rows) for rows in self.sections.values())


def _check_ident(name: str) -> None:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe SQL identifier in export policy: {name!r}")


def _jsonable(value: Any) -> Any:
    """Make a database value JSON-serialisable without losing information.

    Timestamps keep their offset (ISO 8601), so an importer can reconstruct the instant; UUIDs and
    Decimals become strings rather than lossy numbers. Unknown types fall back to ``str`` — an
    export must never fail because of one exotic column.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        # Binary columns are blob *references* elsewhere in this schema; if one ever holds bytes,
        # say so rather than dumping unreadable escapes into the JSON.
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _select(spec: TableSpec, scope: ExportScope) -> tuple[str, str] | None:
    """The statement plus the manifest note for one table, or ``None`` if it has no place here.

    The note matters: a table can be absent, whole or narrowed, and the manifest has to say which.
    "Absent" and "narrowed to you" are different answers to "is this everything?".
    """
    # S608 below: identifiers are validated against _IDENT in ExportPolicy.__post_init__ and come
    # from code, never from a request. The only request-derived value, the subject id, IS bound.
    whole = spec.shared and scope is ExportScope.HOUSEHOLD
    if whole:
        return f"SELECT * FROM {spec.name} ORDER BY 1", ""  # noqa: S608

    terms = [f"{c} = :subject" for c in spec.personal_columns]
    terms += [f"{c} = :subject_text" for c in spec.personal_text_columns]
    if spec.shared_when is not None and scope is ExportScope.HOUSEHOLD:
        terms.append(f"{spec.shared_when[0]} = :shared_value")
    if not terms:
        return None
    where = " OR ".join(terms)
    note = (
        "auf deine Person eingeengt — die Zeilen anderer Mitglieder gehören ihnen"
        if scope is ExportScope.HOUSEHOLD
        else ""
    )
    return f"SELECT * FROM {spec.name} WHERE {where} ORDER BY 1", note  # noqa: S608


async def collect_export(
    session: AsyncSession,
    *,
    policy: ExportPolicy,
    scope: ExportScope,
    subject_id: uuid.UUID | None = None,
    max_rows: int | None = None,
) -> ExportResult:
    """Read every allowed table on the caller's own session and return redacted, JSON-ready rows.

    ``subject_id`` is the person running the export. Required for
    :attr:`ExportScope.PERSONAL`, and also used in a household export for the tables marked
    ``subject_scoped``. The caller's session decides tenancy (RLS); this function never widens it.
    """
    if subject_id is None and (
        scope is ExportScope.PERSONAL or any(not s.shared for s in policy.tables)
    ):
        # Also required for a HOUSEHOLD export as soon as the policy marks a table
        # ``subject_scoped`` — without the id those rows could not be narrowed to the caller and
        # would fall back to household-wide, which is the disclosure this flag exists to prevent.
        raise ValueError("this export needs the id of the person running it")

    sections: dict[str, list[dict[str, Any]]] = {}
    skipped: dict[str, str] = {}
    narrowed: dict[str, str] = {}
    collected = 0

    for spec in policy.tables:
        statement = _select(spec, scope)
        if statement is None:
            skipped[spec.name] = (
                "gehört dem ganzen Haushalt und ist keiner Person zuzuordnen — "
                "nur im Haushalts-Export enthalten"
            )
            continue
        sql, note = statement
        if note:
            narrowed[spec.name] = note
        params: dict[str, Any] = {}
        if ":subject " in f"{sql} " or ":subject\n" in sql:
            params["subject"] = subject_id
        if ":subject_text" in sql:
            params["subject_text"] = f"{spec.personal_text_prefix}{subject_id}"
        if ":shared_value" in sql and spec.shared_when is not None:
            params["shared_value"] = spec.shared_when[1]
        result = await session.execute(text(sql), params)
        redacted = policy.redact.get(spec.name, frozenset())
        rows: list[dict[str, Any]] = []
        for mapping in result.mappings():
            rows.append(
                {
                    key: (REDACTED if key in redacted else _jsonable(value))
                    for key, value in mapping.items()
                }
            )
        sections[spec.name] = rows
        collected += len(rows)
        if max_rows is not None and collected > max_rows:
            # Stop here rather than after the archive exists — see ExportTooLarge.
            raise ExportTooLarge(collected, max_rows)

    return ExportResult(sections=sections, skipped=skipped, narrowed=narrowed)


def redacted_columns(policy: ExportPolicy) -> Sequence[str]:
    """``table.column`` for everything the policy withholds — goes into the manifest verbatim, so
    the export states plainly what it kept back instead of quietly dropping it."""
    return sorted(f"{table}.{column}" for table, cols in policy.redact.items() for column in cols)
