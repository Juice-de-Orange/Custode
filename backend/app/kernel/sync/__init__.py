"""Sync-Batch engine (ARCHITECTURE §10) — the single write path for offline-capable entities.

A client pushes ops ``[{client_op_id, entity, id, base_version, op, fields}]``; the server applies
them with **LWW per field group** (only fields present in an op are written, so independent edits —
``checked`` vs ``label`` — never clobber each other), dedupes by ``client_op_id`` (idempotent), and
returns the authoritative server state. Generic via ``ModuleSpec``; strategy = ADR-0032."""
