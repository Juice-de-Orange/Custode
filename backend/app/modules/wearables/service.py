"""wearables use-cases (P9-S5, ADR-0081).

The ONLY place that encrypts or decrypts tokens — one location makes "plaintext is never
persisted" a property you can check by reading one file (the 9-S2 rule).

Every read filters ``member_id`` even though migration 0069's RLS already does: defence in
depth, and it keeps the 404-for-foreign behaviour explicit rather than relying on an empty
result set. The RLS is the guarantee; this is the readable intent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.crypto import require_secretbox
from app.kernel.http.problem import ProblemException
from app.kernel.ports.wearable import WearableAuthError, WearableOAuthPort
from app.logging import get_logger
from app.modules.accounts import api as accounts_api
from app.modules.wearables.models import WearableConnection, WearableDailyRow
from app.modules.wearables.schemas import ConnectionResponse
from app.modules.wearables.state import PendingConnect, issue_state, pop_state
from app.modules.wearables.tokens import encode_tokens
from app.modules.wearables.types import ALL_CONSENT_TYPES, PROVIDER_OURA, scopes_for

_log = get_logger("wearables")

#: Which stored columns a consent type covers. Withdrawing a type NULLs exactly these.
_COLUMNS_BY_CONSENT: dict[str, tuple[str, ...]] = {
    "wearable_sleep": ("sleep_score", "sleep_minutes"),
    "wearable_readiness": ("readiness",),
    "wearable_activity": ("steps", "active_kcal"),
    "wearable_heartrate": ("rhr",),
}


async def require_enabled(session: AsyncSession, *, household_id: uuid.UUID) -> None:
    """403 unless the household has the ``wearables`` flag on (default off).

    Enforced server-side, not just in the UI: for health data, "switched off" has to mean the
    API refuses. Reads and DELETE deliberately skip this check — turning the flag off must not
    lock a member out of their own data or prevent them from deleting it."""
    flags = await accounts_api.household_flags(session, household_id=household_id)
    if not flags.get("wearables", False):
        raise ProblemException(
            slug="feature_disabled",
            title="Wearables sind nicht aktiviert",
            status=403,
            detail="Diese Funktion ist für deinen Haushalt ausgeschaltet.",
        )


async def get_connection(
    session: AsyncSession, *, member_id: uuid.UUID, connection_id: uuid.UUID
) -> WearableConnection:
    """One of the caller's connections. Foreign or missing → 404 — identical answers, so the
    response never reveals that somebody else's connection exists. Admins get 404 too: there is
    no privileged read of health data (N-2)."""
    conn = await session.get(WearableConnection, connection_id)
    if conn is None or conn.member_id != member_id:
        raise ProblemException(slug="not_found", title="Verbindung nicht gefunden", status=404)
    return conn


async def list_connections(
    session: AsyncSession, *, member_id: uuid.UUID
) -> list[WearableConnection]:
    """The caller's connections, oldest first (stable UI order)."""
    rows = await session.scalars(
        select(WearableConnection)
        .where(WearableConnection.member_id == member_id)
        .order_by(WearableConnection.created_at)
    )
    return list(rows)


async def to_response(session: AsyncSession, conn: WearableConnection) -> ConnectionResponse:
    """Wire shape incl. the folded consent state. ``has_tokens`` stands in for the credentials."""
    consents = await accounts_api.effective_consents(
        session, subject_user_id=conn.member_id, types=ALL_CONSENT_TYPES
    )
    return ConnectionResponse(
        id=conn.id,
        member_id=conn.member_id,
        provider=conn.provider,
        status=conn.status,
        has_tokens=conn.tokens_enc is not None,
        consent_types=[t for t in ALL_CONSENT_TYPES if consents.get(t)],
        scopes=list(conn.scopes or []),
        last_sync_at=conn.last_sync_at,
        last_error=conn.last_error,
    )


async def begin_connect(
    session: AsyncSession,
    *,
    oauth: WearableOAuthPort,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    consent_types: list[str],
    redirect_uri: str,
) -> str:
    """Mint the state and build the provider URL.

    Order matters. The crypto key is demanded HERE, before the user ever leaves for the
    provider: without it the callback could not store the tokens, and the user would be left
    with a granted authorisation in their Oura account that we silently dropped. Fail before
    sending them away, not after they come back."""
    if await session.scalar(
        select(WearableConnection.id).where(
            WearableConnection.member_id == member_id,
            WearableConnection.provider == PROVIDER_OURA,
        )
    ):
        raise ProblemException(
            slug="connection_exists",
            title="Verbindung besteht bereits",
            status=409,
            detail="Trenne die bestehende Verbindung, bevor du sie neu einrichtest.",
        )
    require_secretbox()  # 503 crypto_unconfigured — fail before the redirect, see docstring
    state = await issue_state(
        PendingConnect(
            user_id=member_id,
            household_id=household_id,
            provider=PROVIDER_OURA,
            consent_types=consent_types,
        )
    )
    try:
        return oauth.authorize_url(
            state=state, scopes=scopes_for(consent_types), redirect_uri=redirect_uri
        )
    except WearableAuthError as exc:
        raise ProblemException(
            slug="wearables_disabled",
            title="Wearable-Anbindung nicht verfügbar",
            status=503,
            detail="Der Betreiber hat die Anbindung nicht konfiguriert.",
        ) from exc


class ConnectRejected(Exception):
    """The callback could not be completed. ``slug`` ends up as a ``?error=`` query parameter —
    the browser gets a redirect, not a problem+json body, so the slug is the whole message."""

    def __init__(self, slug: str) -> None:
        super().__init__(slug)
        self.slug = slug


async def complete_connect(
    session: AsyncSession,
    *,
    oauth: WearableOAuthPort,
    pending: PendingConnect,
    code: str,
    redirect_uri: str,
) -> WearableConnection:
    """Exchange the code and persist connection + consent in ONE transaction.

    Atomicity is the point: data collected without a recorded legal basis is exactly what Art. 9
    forbids, so the consent rows must not be able to survive a failure that drops the connection,
    or vice versa."""
    box = require_secretbox()
    try:
        tokens = await oauth.exchange_code(code=code, redirect_uri=redirect_uri)
    except WearableAuthError as exc:
        _log.warning("wearable_exchange_failed", category=exc.category, provider=pending.provider)
        raise ConnectRejected(exc.category) from exc

    conn = WearableConnection(
        household_id=pending.household_id,
        member_id=pending.user_id,
        provider=pending.provider,
        tokens_enc=encode_tokens(box, tokens),
        token_expires_at=tokens.expires_at,
        scopes=list(tokens.scopes),
        status="active",
    )
    session.add(conn)
    await accounts_api.record_consents(
        session,
        household_id=pending.household_id,
        subject_user_id=pending.user_id,
        actor_id=pending.user_id,
        grants=pending.consent_types,
    )
    await session.flush()
    # Aggregate + category only — never a token, code, state or the member's provider identity.
    _log.info("wearable_connected", provider=pending.provider, types=len(pending.consent_types))
    return conn


async def _purge_types(
    session: AsyncSession, *, member_id: uuid.UUID, consent_types: set[str]
) -> None:
    """NULL the stored values of the given types. Art. 9's "delete button that really deletes"
    applies to withdrawal too — a revoked type must leave no residue behind."""
    columns = {col: None for t in consent_types for col in _COLUMNS_BY_CONSENT.get(t, ())}
    if not columns:
        return
    await session.execute(
        update(WearableDailyRow).where(WearableDailyRow.member_id == member_id).values(**columns)
    )


async def update_consents(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    connection_id: uuid.UUID,
    consent_types: list[str],
) -> WearableConnection | None:
    """Diff the ledger against the requested set; grant/revoke accordingly.

    Withdrawing the LAST type deletes the connection outright (returns ``None``): a connection
    with no consented type has no purpose and no legal basis, so leaving it around as an inert
    row would be exactly the kind of quiet data retention Art. 9 targets."""
    conn = await get_connection(session, member_id=member_id, connection_id=connection_id)
    current = await accounts_api.effective_consents(
        session, subject_user_id=member_id, types=ALL_CONSENT_TYPES
    )
    active = {t for t in ALL_CONSENT_TYPES if current.get(t)}
    wanted = set(consent_types)
    grants, revokes = wanted - active, active - wanted

    if grants or revokes:
        await accounts_api.record_consents(
            session,
            household_id=household_id,
            subject_user_id=member_id,
            actor_id=member_id,
            grants=sorted(grants),
            revokes=sorted(revokes),
        )
    if revokes:
        await _purge_types(session, member_id=member_id, consent_types=revokes)

    if not wanted:
        await _delete_rows(session, member_id=member_id, connection=conn)
        return None
    conn.scopes = scopes_for(sorted(wanted))
    await session.flush()
    return conn


async def _delete_rows(
    session: AsyncSession, *, member_id: uuid.UUID, connection: WearableConnection
) -> None:
    """Hard-delete the connection and every daily row of that provider — no tombstone (the table
    has a CHECK forbidding one). The consent ledger is append-only and stays: it is the record
    that consent once existed and was withdrawn, which is exactly what has to be auditable."""
    await session.execute(
        delete(WearableDailyRow).where(
            WearableDailyRow.member_id == member_id,
            WearableDailyRow.provider == connection.provider,
        )
    )
    await session.delete(connection)
    await session.flush()


async def delete_connection(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> None:
    """Disconnect: revoke every consent, erase the data, drop the connection.

    Deliberately works WITHOUT a crypto key and with the provider switched off — deleting must
    never depend on an integration being reachable, or a member could be unable to get rid of
    their health data during an outage."""
    conn = await get_connection(session, member_id=member_id, connection_id=connection_id)
    current = await accounts_api.effective_consents(
        session, subject_user_id=member_id, types=ALL_CONSENT_TYPES
    )
    active = sorted(t for t in ALL_CONSENT_TYPES if current.get(t))
    if active:
        await accounts_api.record_consents(
            session,
            household_id=household_id,
            subject_user_id=member_id,
            actor_id=member_id,
            revokes=active,
        )
    await _delete_rows(session, member_id=member_id, connection=conn)
    _log.info("wearable_disconnected", provider=conn.provider)


async def consume_state(token: str) -> PendingConnect:
    """Single-use state lookup. Unknown/expired/replayed all collapse into one rejection."""
    pending = await pop_state(token)
    if pending is None:
        raise ConnectRejected("state_invalid")
    return pending


def now_utc() -> datetime:
    """Injectable clock seam (mirrors the calendar sync's ``now`` parameter)."""
    return datetime.now(UTC)
