from __future__ import annotations

from typing import Protocol


class PaymentsPort(Protocol):
    """Paddle as Merchant of Record (ADR-010). Inbound webhooks are signature-
    verified and replay-protected before async processing."""

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool: ...
