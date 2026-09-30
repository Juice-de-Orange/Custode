"""Exported service interface for ``capture``. No other module consumes capture (the dependency is
one-way: capture -> shopping.api/tasks.api), so this surface is intentionally empty — it exists for
the convention and as the seam for future cross-module callers."""

__all__: list[str] = []
