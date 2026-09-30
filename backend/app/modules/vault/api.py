"""Exported service interface for ``vault``. Empty — no module reacts synchronously; the vault is
self-contained client-side-encrypted storage. Cross-module reactions (if any) consume ``vault.*``
domain events. The server never decrypts vault contents."""

__all__: list[str] = []
