"""Household feature flags (ARCHITECTURE §8.5). A household's effective flags are the DEFAULTs,
overlaid by operator-level global flags (``settings.feature_flags``), overlaid by the household
admin's ``households.settings_json``. The exact same defaults + merge are mirrored in the web
(``web/src/lib/flags.ts``) so UI and API decide identically. Pure + side-effect-free."""

from __future__ import annotations

from collections.abc import Mapping

# Effective default flags for every household. Core modules on; optional/enhancement modules off;
# ``marketplace_children`` is a child-safety default (CLAUDE.md: marketplace for children off by
# default). Adding a key here (and in web/src/lib/flags.ts) is how a new module becomes flaggable.
DEFAULT_HOUSEHOLD_FLAGS: dict[str, bool] = {
    "recipes": True,
    "mealplanner": True,
    "shopping": True,
    "calendar": True,
    "tasks": True,
    "marketplace": True,
    "marketplace_children": False,  # hard child-safety default
    "vault": True,
    "messaging": True,
    "guides": True,
    "notes": True,
    "finances": False,
    "wearables": False,
    "weather": False,
    "ai": False,
}


def get_household_flags(
    settings_json: Mapping[str, object] | None,
    *,
    global_flags: Mapping[str, bool],
) -> dict[str, bool]:
    """Merge DEFAULT ← global (operator) ← settings_json (household admin). The output keys are
    exactly the DEFAULT keys — unknown keys in either source are ignored — and every value is a
    bool. Deterministic and side-effect-free."""
    merged = dict(DEFAULT_HOUSEHOLD_FLAGS)
    for source in (global_flags, settings_json or {}):
        for key in DEFAULT_HOUSEHOLD_FLAGS:
            if key in source:
                merged[key] = bool(source[key])
    return merged
