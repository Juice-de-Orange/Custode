"""Single wiring point for outbox event handlers.

The worker imports THIS module — never a feature module — so the boundary holds
(import-linter forbids ``app.kernel`` → ``app.modules``): feature modules only *emit*
events (``kernel/events/emit.py``); their handlers live in the kernel and are bound here.
Keeping the registry in the kernel means the worker never has to import an
accounts/recipes/… package to dispatch.

An event whose type has no registered handler is marked processed immediately (a harmless
no-op delivery).
"""

from __future__ import annotations

from functools import lru_cache

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.handlers import register_handlers


@lru_cache(maxsize=1)
def get_dispatcher() -> OutboxDispatcher:
    """Process-wide dispatcher with every handler registered. Cached so the worker builds
    the handler graph once. Tests that need a clean graph call ``get_dispatcher.cache_clear()``."""
    dispatcher = OutboxDispatcher()
    register_handlers(dispatcher)  # invalidation bridge: member.* -> per-household SSE hint
    return dispatcher
