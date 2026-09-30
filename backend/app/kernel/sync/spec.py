"""A module declares which entities are syncable + their writable/readable fields, so the generic
engine (``apply.py``) can merge ops without knowing the concrete domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.kernel.db.base import Base


@dataclass(frozen=True)
class EntitySpec:
    entity: str  # wire name, e.g. "shopping_item"
    model: type[Base]
    fields: frozenset[str]  # writable via sync (the union of all field groups)
    required_on_create: frozenset[str]
    read_fields: frozenset[str]  # returned in the server-state response
    uuid_fields: frozenset[str] = frozenset()  # coerce str -> UUID before assigning
    owner_field: str | None = None  # set to the acting user_id on create (e.g. "created_by")
    # Trigger field -> owner column: a present trigger (e.g. reserve/checked) sets the owner column
    # to the acting user (NULL when falsy). The owner column is not client-writable -> unspoofable.
    server_owner_fields: Mapping[str, str] = field(default_factory=dict)
    # Field -> domain event type, emitted (additively) when that field flips falsy -> truthy on an
    # op (e.g. shopping_item "checked" -> "shopping.item.checked"). Payload {"id", "user_id"}. Keeps
    # the generic engine domain-agnostic — only the module's spec names the event; consumers react
    # via the outbox (e.g. capture activates an armed task on shopping.item.checked).
    transition_events: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleSpec:
    module: str  # URL segment, e.g. "shopping"
    entities: dict[str, EntitySpec] = field(default_factory=dict)
