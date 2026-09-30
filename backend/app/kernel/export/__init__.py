"""Data export mechanism for the GDPR subject rights (Art. 15 / Art. 20).

Pure machinery: it is handed a policy (which tables, which columns to redact, how a row is tied
to a person) and produces JSON-serialisable sections, then packs them into a ZIP. The kernel
deliberately knows **no** module table names — the policy is assembled at the composition root,
exactly like the retention reaper's table list (ARCHITECTURE §9, ADR-0039).
"""

from .archive import Attachment, build_export_archive, safe_entry_name
from .collect import (
    REDACTED,
    ExportPolicy,
    ExportResult,
    ExportScope,
    ExportTooLarge,
    TableSpec,
    collect_export,
    redacted_columns,
)

__all__ = [
    "REDACTED",
    "Attachment",
    "ExportPolicy",
    "ExportResult",
    "ExportScope",
    "ExportTooLarge",
    "TableSpec",
    "build_export_archive",
    "collect_export",
    "redacted_columns",
    "safe_entry_name",
]
