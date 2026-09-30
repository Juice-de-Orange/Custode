from __future__ import annotations

from app.main import create_app


def test_openapi_schema_builds() -> None:
    """The OpenAPI schema builds and carries the business routes. Health/readiness are
    infra (include_in_schema=False) and stay out of the client contract."""
    schema = create_app().openapi()
    assert schema["info"]["title"].endswith("API")
    assert schema["openapi"].startswith("3.")
    paths = schema.get("paths", {})
    # Auth + household routes are part of the client contract.
    assert "/v1/auth/login" in paths
    assert "/v1/auth/register" in paths
    assert "/v1/auth/me" in paths
    assert "/v1/auth/totp/setup" in paths
    assert "/v1/auth/passkeys/login/begin" in paths
    assert "/v1/households" in paths
    # Tasks routes (P4-S1) are part of the client contract.
    assert "/v1/tasks/templates" in paths
    assert "/v1/tasks/instances" in paths
    assert "/v1/tasks/instances/{instance_id}/complete" in paths
    assert "/v1/tasks/rooms" in paths
    assert "/v1/tasks/heatmap" in paths
    # Economy routes (P4-S2) are part of the client contract.
    assert "/v1/economy/balance" in paths
    assert "/v1/economy/ledger" in paths
    assert "/v1/economy/corrections" in paths
    assert "/v1/economy/rewards" in paths
    assert "/v1/economy/rewards/{reward_id}/redeem" in paths
    assert "/v1/economy/redemptions" in paths
    assert "/v1/economy/thanks" in paths
    assert "/v1/economy/challenge" in paths
    assert "/v1/economy/fairness" in paths
    # Marketplace routes (P4-S8a) are part of the client contract.
    assert "/v1/marketplace/listings" in paths
    assert "/v1/marketplace/listings/{listing_id}/accept" in paths
    assert "/v1/marketplace/listings/{listing_id}/settle" in paths
    assert "/v1/marketplace/auto-accept" in paths
    # Capture routes (P4-S9a) are part of the client contract.
    assert "/v1/capture" in paths
    assert "/v1/capture/inbox" in paths
    assert "/v1/capture/{capture_id}/confirm" in paths
    # Calendar routes (P5-S1) are part of the client contract.
    assert "/v1/calendar/events" in paths
    assert "/v1/calendar/events/{event_id}" in paths
    assert "/v1/calendar/events/{event_id}/move-occurrence" in paths
    # Weather routes (P5-S7) are part of the client contract.
    assert "/v1/weather" in paths
    assert "/v1/weather/location" in paths
    assert "/v1/weather/geocode" in paths
    # Scheduling routes (P5-S8) are part of the client contract.
    assert "/v1/scheduling/slots" in paths
    # Mealplanner routes (P6-S1) are part of the client contract.
    assert "/v1/mealplan" in paths
    assert "/v1/mealplan/slot" in paths
    assert "/v1/mealplan/suggest" in paths
    assert "/v1/mealplan/suggest-week" in paths
    assert "/v1/mealplan/copy" in paths
    assert "/v1/mealplan/slot/cook-task" in paths
    assert "/v1/mealplan/slot/prep-task" in paths
    assert "/v1/mealplan/nutrition" in paths
    # Notes routes (P7-S1) are part of the client contract.
    assert "/v1/notes" in paths
    assert "/v1/notes/{note_id}" in paths
    assert "/v1/notes/{note_id}/versions" in paths
    assert "/v1/notes/{note_id}/restore" in paths
    assert "/v1/notes/{note_id}/to-task" in paths
    # Messaging/Briefe routes (P7-S4) are part of the client contract.
    assert "/v1/letters" in paths
    assert "/v1/letters/{letter_id}" in paths
    assert "/v1/letters/unread-count" in paths
    assert "/v1/letters/{letter_id}/to-task" in paths
    # Guides / Anleitungen routes (P7-S6) are part of the client contract.
    assert "/v1/guides" in paths
    assert "/v1/guides/{guide_id}" in paths
    # Comments routes (P7-S7) are part of the client contract.
    assert "/v1/comments" in paths
    assert "/v1/comments/{comment_id}" in paths
    # Object-links routes (P7-S8) are part of the client contract.
    assert "/v1/links" in paths
    assert "/v1/links/{link_id}" in paths
    # Vault routes (P7-S13) are part of the client contract.
    assert "/v1/vault/keys" in paths
    assert "/v1/vault/items" in paths
    assert "/v1/vault/items/{item_id}" in paths
    # Health endpoints are deliberately excluded.
    assert "/healthz" not in paths
    assert "/readyz" not in paths
