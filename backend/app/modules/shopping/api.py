"""Exported service interface — the only allowed cross-module entry into ``shopping``."""

from app.modules.shopping.service import (
    apply_shopping_batch,
    ensure_default_list,
    pull_shopping,
)
from app.modules.shopping.spec import SHOPPING_SPEC

__all__ = ["SHOPPING_SPEC", "apply_shopping_batch", "ensure_default_list", "pull_shopping"]
