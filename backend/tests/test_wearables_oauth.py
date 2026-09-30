"""Pure unit tests for the Oura OAuth adapter, the token format contract and the consent fold
(P9-S5, ADR-0081). No Docker, no DB — the whole slice's logic that can be tested without either.

The token-response tests use ``httpx.MockTransport`` (the ``test_feedback_forward`` pattern) so
the real adapter code path runs, wire format included, without a network."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.adapters.null import NullWearableOAuth
from app.adapters.oura import OuraOAuth
from app.adapters.oura.oauth import AUTHORIZE_URL, _parse_tokens
from app.kernel.crypto import SecretBox, SecretBoxError, generate_key
from app.kernel.ports.wearable import WearableAuthError, WearableTokens
from app.modules.wearables.tokens import decode_tokens, encode_tokens
from app.modules.wearables.types import (
    ALL_CONSENT_TYPES,
    CONSENT_ACTIVITY,
    CONSENT_HEARTRATE,
    CONSENT_READINESS,
    CONSENT_SLEEP,
    scopes_for,
)
from app.settings import Settings
from app.wearable_factory import build_wearable_oauth

REDIRECT_URI = "https://custode.example/v1/wearables/oura/callback"

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before monkeypatching (avoid self-recursion)


def _settings(**kw: object) -> Settings:
    # _env_file=None so a developer's local .env cannot change the assertions.
    base: dict[str, object] = {
        "_env_file": None,
        "oura_client_id": "cid",
        "oura_client_secret": "sec",
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


def _adapter(monkeypatch: pytest.MonkeyPatch, handler: object) -> OuraOAuth:
    monkeypatch.setattr(
        "app.adapters.oura.oauth.httpx.AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)),
    )
    return OuraOAuth(_settings())


# ------------------------------------------------------------------ scope mapping


def test_scopes_are_the_union_of_the_chosen_types() -> None:
    # Three consent types share one provider scope — asking for all three must not request it
    # three times, and asking for sleep only must NOT pull in the heart-rate scope.
    assert scopes_for([CONSENT_SLEEP]) == ["daily"]
    assert scopes_for([CONSENT_SLEEP, CONSENT_READINESS, CONSENT_ACTIVITY]) == ["daily"]
    assert scopes_for([CONSENT_SLEEP, CONSENT_HEARTRATE]) == ["daily", "heartrate"]
    assert scopes_for([]) == []


def test_scope_order_is_stable_regardless_of_input_order() -> None:
    assert scopes_for([CONSENT_HEARTRATE, CONSENT_SLEEP]) == scopes_for(
        [CONSENT_SLEEP, CONSENT_HEARTRATE]
    )


# ------------------------------------------------------------------ authorize URL


def test_authorize_url_carries_every_required_parameter() -> None:
    url = OuraOAuth(_settings()).authorize_url(
        state="st-123", scopes=["daily", "heartrate"], redirect_uri=REDIRECT_URI
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["scope"] == ["daily heartrate"]
    assert query["state"] == ["st-123"]
    # The client SECRET must never travel via the browser — it belongs to the token exchange.
    assert "sec" not in url


async def test_exchange_sends_the_identical_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classic breakage: authorize and exchange building the URI slightly differently.
    Providers compare them byte-for-byte."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"})

    adapter = _adapter(monkeypatch, handler)
    authorize = adapter.authorize_url(state="s", scopes=["daily"], redirect_uri=REDIRECT_URI)
    await adapter.exchange_code(code="the-code", redirect_uri=REDIRECT_URI)

    assert seen["redirect_uri"] == parse_qs(urlparse(authorize).query)["redirect_uri"][0]
    assert seen["grant_type"] == "authorization_code"
    assert seen["code"] == "the-code"
    assert seen["client_secret"] == "sec"  # confidential client authenticates the exchange


async def test_refresh_uses_the_refresh_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2"})

    tokens = await _adapter(monkeypatch, handler).refresh(refresh_token="rt1")
    assert seen["grant_type"] == "refresh_token"
    assert seen["refresh_token"] == "rt1"
    # Providers ROTATE refresh tokens: the answer replaces the stored value wholesale.
    assert tokens.refresh_token == "rt2"


# ------------------------------------------------------------------ token response parsing


def test_parse_tokens_reads_a_full_response() -> None:
    tokens = _parse_tokens(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "daily heartrate",
            "some_future_field": "ignored",  # forward compatibility (ARCHITECTURE §8.2)
        },
        category="exchange_failed",
    )
    assert (tokens.access_token, tokens.refresh_token) == ("at", "rt")
    assert tokens.scopes == ["daily", "heartrate"]
    assert tokens.expires_at is not None


def test_parse_tokens_tolerates_a_minimal_response() -> None:
    tokens = _parse_tokens({"access_token": "at"}, category="exchange_failed")
    assert tokens.refresh_token is None
    assert tokens.token_type == "Bearer"
    assert tokens.scopes == []
    assert tokens.expires_at is None


@pytest.mark.parametrize(
    "payload",
    [
        {},  # no access token at all
        {"access_token": None},
        {"access_token": 42},
        {"refresh_token": "rt"},  # refresh without access is useless
        "not-a-dict",
    ],
)
def test_parse_tokens_rejects_a_response_without_a_usable_access_token(payload: object) -> None:
    with pytest.raises(WearableAuthError):
        _parse_tokens(payload, category="exchange_failed")


async def test_http_error_becomes_a_categorised_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch, lambda request: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(WearableAuthError) as exc:
        await adapter.exchange_code(code="c", redirect_uri=REDIRECT_URI)
    assert exc.value.category == "exchange_failed"


async def test_non_json_body_becomes_an_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch, lambda request: httpx.Response(200, text="<html>nope"))
    with pytest.raises(WearableAuthError) as exc:
        await adapter.refresh(refresh_token="rt")
    assert exc.value.category == "refresh_failed"


# ------------------------------------------------------------------ Null adapter + factory


async def test_null_adapter_refuses_on_every_method() -> None:
    """The neutral no-op of an authorisation flow is "refuse", not a blank answer — handing out
    an authorize URL that cannot be completed would leave a dangling grant in the user's Oura
    account (the NullCaldav lesson, ADR-0079)."""
    null = NullWearableOAuth()
    with pytest.raises(WearableAuthError) as exc:
        null.authorize_url(state="s", scopes=[], redirect_uri=REDIRECT_URI)
    assert exc.value.category == "wearables_disabled"
    with pytest.raises(WearableAuthError):
        await null.exchange_code(code="c", redirect_uri=REDIRECT_URI)
    with pytest.raises(WearableAuthError):
        await null.refresh(refresh_token="rt")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, OuraOAuth),  # enabled + both credentials
        ({"oura_enabled": False}, NullWearableOAuth),  # operator kill switch
        ({"oura_client_id": None}, NullWearableOAuth),  # credentials incomplete
        ({"oura_client_secret": None}, NullWearableOAuth),
    ],
)
def test_factory_matrix(kwargs: dict[str, object], expected: type) -> None:
    assert isinstance(build_wearable_oauth(_settings(**kwargs)), expected)


# ------------------------------------------------------------------ token storage format


def _box() -> SecretBox:
    return SecretBox(generate_key())


def test_tokens_round_trip() -> None:
    box = _box()
    original = WearableTokens(
        access_token="at", refresh_token="rt", token_type="Bearer", scopes=["daily"]
    )
    stored = encode_tokens(box, original)
    assert stored.startswith("v1:")
    restored = decode_tokens(box, stored)
    assert restored.access_token == "at"
    assert restored.refresh_token == "rt"
    assert restored.scopes == ["daily"]


def test_stored_value_does_not_contain_the_plaintext() -> None:
    box = _box()
    stored = encode_tokens(box, WearableTokens(access_token="super-secret-access-token"))
    assert "super-secret-access-token" not in stored


def test_decode_rejects_tampering() -> None:
    box = _box()
    stored = encode_tokens(box, WearableTokens(access_token="at"))
    with pytest.raises(SecretBoxError):
        decode_tokens(box, stored[:-2] + "xy")


def test_decode_rejects_a_foreign_key() -> None:
    stored = encode_tokens(_box(), WearableTokens(access_token="at"))
    with pytest.raises(SecretBoxError):
        decode_tokens(_box(), stored)


@pytest.mark.parametrize(
    "payload", ['{"refresh_token": "rt"}', '{"access_token": ""}', '{"access_token": 5}', "[]"]
)
def test_decode_rejects_a_wrong_shape(payload: str) -> None:
    box = _box()
    with pytest.raises(SecretBoxError):
        decode_tokens(box, box.encrypt(payload))


def test_decode_rejects_an_unknown_scheme() -> None:
    box = _box()
    stored = encode_tokens(box, WearableTokens(access_token="at"))
    with pytest.raises(SecretBoxError):
        decode_tokens(box, stored.replace("v1:", "v9:", 1))


# ------------------------------------------------------------------ consent fold (property)


def _fold(decisions: list[tuple[str, str]]) -> dict[str, bool]:
    """Pure reference implementation of what ``accounts.effective_consents`` does in SQL:
    latest decision per type wins, unmentioned types are False."""
    latest: dict[str, str] = {}
    for consent_type, action in decisions:
        latest[consent_type] = action
    return {t: latest.get(t) == "grant" for t in ALL_CONSENT_TYPES}


@given(
    st.lists(
        st.tuples(st.sampled_from(ALL_CONSENT_TYPES), st.sampled_from(["grant", "revoke"])),
        max_size=25,
    )
)
def test_fold_never_reports_a_type_that_was_never_granted(decisions: list[tuple[str, str]]) -> None:
    """The invariant that matters legally: absence of consent is not consent. No sequence of
    ledger rows may make a type effective that was never granted."""
    effective = _fold(decisions)
    granted = {t for t, action in decisions if action == "grant"}
    for consent_type, is_on in effective.items():
        if is_on:
            assert consent_type in granted


@given(
    st.lists(
        st.tuples(st.sampled_from(ALL_CONSENT_TYPES), st.sampled_from(["grant", "revoke"])),
        max_size=25,
    )
)
def test_fold_matches_the_last_decision_per_type(decisions: list[tuple[str, str]]) -> None:
    effective = _fold(decisions)
    for consent_type in ALL_CONSENT_TYPES:
        relevant = [a for t, a in decisions if t == consent_type]
        assert effective[consent_type] == bool(relevant and relevant[-1] == "grant")


@given(st.lists(st.sampled_from(ALL_CONSENT_TYPES), max_size=6))
def test_a_revoke_after_any_history_always_wins(types: list[str]) -> None:
    """Withdrawal is final until re-granted — appending a revoke must switch the type off no
    matter what came before."""
    history = [(t, "grant") for t in types]
    assert _fold([*history, (CONSENT_SLEEP, "revoke")])[CONSENT_SLEEP] is False


def test_consent_types_are_json_serialisable_for_the_redis_state() -> None:
    # state.py round-trips the pending consent selection through JSON; a non-serialisable
    # vocabulary would only blow up at runtime, in the callback, after the provider round trip.
    assert json.loads(json.dumps(list(ALL_CONSENT_TYPES))) == list(ALL_CONSENT_TYPES)
