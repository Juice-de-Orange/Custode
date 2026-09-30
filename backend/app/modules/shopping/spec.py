"""Sync field declaration for ``shopping`` (consumed by kernel/sync). Field groups (ADR-0032):
item Group A = {label,qty,unit,category}, Group B = {checked}. ``checked``/``reserve`` are
server-owner triggers → the server stamps ``checked_by``/``reserved_by`` (unspoofable; those
columns are not client-writable). ``created_by`` is set on create."""

from __future__ import annotations

from app.kernel.sync.spec import EntitySpec, ModuleSpec
from app.modules.shopping.models import ShoppingBasic, ShoppingItem, ShoppingList

_ITEM_READ = frozenset(
    {
        "list_id",
        "label",
        "qty",
        "unit",
        "category",
        "checked",
        "source",
        "notes",
        "checked_by",
        "reserved_by",
    }
)

SHOPPING_SPEC = ModuleSpec(
    module="shopping",
    entities={
        "shopping_list": EntitySpec(
            entity="shopping_list",
            model=ShoppingList,
            fields=frozenset({"name", "category_order"}),
            required_on_create=frozenset({"name"}),
            read_fields=frozenset({"name", "category_order"}),
        ),
        "shopping_item": EntitySpec(
            entity="shopping_item",
            model=ShoppingItem,
            fields=frozenset(
                {"list_id", "label", "qty", "unit", "category", "checked", "source", "notes"}
            ),
            required_on_create=frozenset({"list_id", "label"}),
            read_fields=_ITEM_READ,
            uuid_fields=frozenset({"list_id"}),
            owner_field="created_by",
            server_owner_fields={"checked": "checked_by", "reserve": "reserved_by"},
            # Checking an item arms action chains (Deo-Fall, KONZEPT §5.17): the capture handler
            # activates a follow-up task on this event. Emitted only on the falsy -> truthy flip.
            transition_events={"checked": "shopping.item.checked"},
        ),
        "shopping_basic": EntitySpec(
            entity="shopping_basic",
            model=ShoppingBasic,
            fields=frozenset({"label", "category"}),
            required_on_create=frozenset({"label"}),
            read_fields=frozenset({"label", "category"}),
            owner_field="created_by",
        ),
    },
)
