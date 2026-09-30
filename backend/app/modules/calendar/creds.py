"""CalDAV credential encoding (P9-S2, ADR-0077). Pure: only ``kernel/crypto`` + ``json``.

The stored ``creds_enc`` value is ONE SecretBox token over the JSON ``{username, password}`` —
the username is often an e-mail (PII), so it stays inside the ciphertext, and the 9-S3 sync
worker needs both parts together anyway. This module is the format contract between the write
path (here) and the future pull-sync worker: decode what encode produced, nothing else. The
``{username, password}`` shape is deliberately Basic-Auth-only — OAuth tokens (Google/Oura)
get their own format in their own slice.
"""

from __future__ import annotations

import json

from app.kernel.crypto import SecretBox, SecretBoxError


def encode_credentials(box: SecretBox, *, username: str, password: str) -> str:
    """Encrypt ``{username, password}`` into the single ``v1:``-prefixed ``creds_enc`` value."""
    return box.encrypt(json.dumps({"username": username, "password": password}))


def decode_credentials(box: SecretBox, value: str) -> tuple[str, str]:
    """Decrypt a ``creds_enc`` value back into ``(username, password)``. Raises ``SecretBoxError``
    on tampering/wrong key (from the box) or a payload that is not the expected JSON shape —
    deliberately without details, mirroring the box's error contract."""
    raw = box.decrypt(value)
    try:
        data = json.loads(raw)
        return str(data["username"]), str(data["password"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretBoxError("invalid payload") from exc
