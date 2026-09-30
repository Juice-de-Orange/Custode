"""Household feature flags (ARCHITECTURE §8.5). The merge is pure, so we property-check it; the
child-safety default (children marketplace off) is asserted explicitly. Pure — runs locally."""

from __future__ import annotations

from app.kernel.config.flags import DEFAULT_HOUSEHOLD_FLAGS, get_household_flags


def test_defaults_all_bool_and_children_marketplace_off() -> None:
    assert all(isinstance(v, bool) for v in DEFAULT_HOUSEHOLD_FLAGS.values())
    assert DEFAULT_HOUSEHOLD_FLAGS["marketplace_children"] is False


def test_output_keys_equal_defaults_and_values_bool() -> None:
    out = get_household_flags(
        {"recipes": 0, "unknown_key": True, "marketplace_children": 1},
        global_flags={"weather": True, "another_unknown": False},
    )
    assert set(out) == set(DEFAULT_HOUSEHOLD_FLAGS)  # unknown keys never leak in
    assert all(isinstance(v, bool) for v in out.values())  # truthy/falsy coerced to bool
    assert out["recipes"] is False  # settings_json override (0 -> False)
    assert out["weather"] is True  # operator global override
    assert out["marketplace_children"] is True  # an admin may opt in (it is a default, not a lock)


def test_none_settings_json_yields_defaults_plus_global() -> None:
    out = get_household_flags(None, global_flags={"ai": True})
    assert out == {**DEFAULT_HOUSEHOLD_FLAGS, "ai": True}


def test_settings_json_wins_over_global() -> None:
    assert get_household_flags({"vault": False}, global_flags={"vault": True})["vault"] is False
