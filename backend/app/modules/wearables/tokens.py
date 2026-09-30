"""OAuth token encoding (P9-S5, ADR-0077/0081). Pure: only ``kernel/crypto``, ``kernel/ports``
and ``json``.

The format contract between the write path (service) and the future refresh worker (9-S6), the
exact analogue of ``modules/calendar/creds.py`` — which states outright that OAuth tokens get
their own format in their own slice. This is that format.

Stored ``tokens_enc`` is ONE SecretBox value over ``{access_token, refresh_token, token_type,
scopes}``. The refresh token is the longest-lived secret in the whole system (it re-mints access
tokens indefinitely), so it belongs inside the ciphertext, not in a column.

``expires_at`` is deliberately NOT part of the payload — it lives in the plaintext column
``token_expires_at`` so the cron can filter on it in SQL without decrypting every row.
"""

from __future__ import annotations

import json

from app.kernel.crypto import SecretBox, SecretBoxError
from app.kernel.ports.wearable import WearableTokens


def encode_tokens(box: SecretBox, tokens: WearableTokens) -> str:
    """Encrypt the secret parts of ``tokens`` into the single ``v1:``-prefixed value."""
    return box.encrypt(
        json.dumps(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "scopes": list(tokens.scopes),
            }
        )
    )


def decode_tokens(box: SecretBox, value: str) -> WearableTokens:
    """Decrypt a ``tokens_enc`` value back into ``WearableTokens`` (without ``expires_at`` —
    the caller adds it from the plaintext column).

    Raises ``SecretBoxError`` on tampering/wrong key (from the box) or on a payload that is not
    the expected shape — deliberately without details, mirroring the box's error contract."""
    raw = box.decrypt(value)
    try:
        data = json.loads(raw)
        access_token = data["access_token"]
        if not isinstance(access_token, str) or not access_token:
            raise SecretBoxError("invalid payload")
        refresh_token = data.get("refresh_token")
        scopes = data.get("scopes") or []
        if not isinstance(scopes, list):
            raise SecretBoxError("invalid payload")
        return WearableTokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=str(data.get("token_type") or "Bearer"),
            scopes=[str(s) for s in scopes],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretBoxError("invalid payload") from exc
