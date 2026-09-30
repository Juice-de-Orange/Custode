"""Server-side secret encryption for third-party credentials (ADR-0077)."""

from app.kernel.crypto.secretbox import (
    SecretBox,
    SecretBoxError,
    generate_key,
    get_secretbox,
    require_secretbox,
)

__all__ = [
    "SecretBox",
    "SecretBoxError",
    "generate_key",
    "get_secretbox",
    "require_secretbox",
]
