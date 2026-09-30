"""HTTP contracts for ``nutrition`` (canonical ingredients). Values + calc land in S5."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class IngredientOut(BaseModel):
    id: uuid.UUID
    name_de: str
    name_en: str
    category: str
    default_unit: str
