"""Betreiber-Konsole auth use-cases (ADR-0015). Operators are a separate identity space (no
household, no RLS). Auth = password + **mandatory** TOTP. These run on an ``ops_readonly`` session
for login (read) / an ``ops_actions`` session for provisioning (write) — never the app role."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.audit.model import AuditEntry
from app.kernel.audit.record import record_audit
from app.kernel.auth import totp, webauthn
from app.kernel.auth.passwords import hash_password, verify_password
from app.kernel.auth.tokens import new_token
from app.kernel.http.problem import ProblemException
from app.modules.backoffice.models import Banner, Operator, OperatorPasskey
from app.modules.backoffice.schemas import (
    AuditLogEntry,
    BannerCreate,
    DailyMetric,
    HouseholdMetadata,
    OpsFeedbackEntry,
    OpsKpis,
    UsageCounters,
)

_HM_COLS = "id, name, created_at, member_count, admin_count"

# Verify against a fixed hash when the operator is unknown, so response timing doesn't reveal
# whether an e-mail exists (mirrors the accounts login path).
_DUMMY_HASH = hash_password("operator-enumeration-guard")


def _normalize(email: str) -> str:
    return email.strip().lower()


async def create_operator(
    session: AsyncSession, *, email: str, password: str, totp_secret: str
) -> Operator:
    """Provision an operator (password + enrolled TOTP). Used by a privileged seed/CLI and tests —
    there is no self-serve operator signup. Runs on an ``ops_actions`` session."""
    operator = Operator(
        email=_normalize(email),
        password_hash=hash_password(password),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    session.add(operator)
    await session.flush()
    return operator


async def list_operators(session: AsyncSession) -> list[Operator]:
    """All operators for the management list (newest first). Runs on ``ops_readonly``. The router
    maps to ``OperatorSummary`` — password_hash/totp_secret never leave this layer."""
    rows = await session.scalars(select(Operator).order_by(Operator.created_at.desc()))
    return list(rows)


class LastActiveOperatorError(Exception):
    """Deactivating this operator would leave zero active operators — total console lockout."""


async def set_operator_active(
    session: AsyncSession, *, operator_id: uuid.UUID, active: bool, actor_id: uuid.UUID
) -> Operator | None:
    """Activate/deactivate an operator (audited). ``None`` if unknown. Idempotent — a no-op state
    change is not re-audited. Refuses to deactivate the LAST active operator (raises
    ``LastActiveOperatorError``); the active rows are locked ``FOR UPDATE`` so two concurrent
    deactivations serialize and cannot both reach zero. Runs on ``ops_actions`` (SELECT+UPDATE on
    operators); the caller additionally guards self-deactivation."""
    operator = await session.get(Operator, operator_id)
    if operator is None:
        return None
    if not active:
        # Lock every currently-active operator; the set is then stable until this txn ends.
        active_ids = set(
            (
                await session.scalars(
                    select(Operator.id).where(Operator.is_active.is_(True)).with_for_update()
                )
            ).all()
        )
        if operator_id not in active_ids:
            return operator  # already inactive (idempotent; also the concurrent-deactivation case)
        if active_ids == {operator_id}:
            raise LastActiveOperatorError
    elif operator.is_active:
        return operator  # already active (idempotent) — nothing to change or audit
    operator.is_active = active
    await record_audit(
        session,
        actor_type="operator",
        actor_id=actor_id,
        action="operator.activated" if active else "operator.deactivated",
        target_type="operator",
        target_id=operator_id,
    )
    await session.flush()
    return operator


async def authenticate_operator(
    session: AsyncSession, *, email: str, password: str, totp_code: str
) -> Operator | None:
    """Verify e-mail + password + mandatory TOTP. Fail-closed: any mismatch (unknown e-mail, wrong
    password, inactive, TOTP not enrolled, wrong code) returns ``None``. Always runs one password
    verify (constant-time vs. enumeration). Read-only — runs on an ``ops_readonly`` session."""
    operator = await session.scalar(select(Operator).where(Operator.email == _normalize(email)))
    password_ok = verify_password(operator.password_hash if operator else _DUMMY_HASH, password)
    if operator is None or not password_ok or not operator.is_active:
        return None
    if not operator.totp_enabled or operator.totp_secret is None:
        return None
    if not totp.verify(operator.totp_secret, totp_code):
        return None
    return operator


# --------------------------------------------------------------- operator passkeys (ADR-0072)
# WebAuthn via the reusable kernel primitives (app.kernel.auth.webauthn); crypto is not hand-rolled.
# Register is keyed off the authenticated operator (cookieless already). Passwordless login is the
# only cookieless-specific bit: the challenge is keyed by an opaque ``flow_id`` returned in the
# response body and echoed back on complete (the ops console has no cookie/CSRF — ADR-0015).
#
# FOLLOW-UP (BUGLOG-worthy): this mirrors the member flow and does NOT yet server-enforce WebAuthn
# user verification (require_user_verification). Platform authenticators (Touch ID / Windows Hello)
# perform UV anyway, so an enrolled passkey is 2-factor in practice; the residual gap is only a
# self-inflicted presence-only security key without a PIN. Hard UV enforcement is blocked on a
# UV-capable test authenticator (soft-webauthn 0.1.3 emits UP-only) — enable it when tooling allows.


async def passkey_register_begin(
    session: AsyncSession, *, operator_id: uuid.UUID, operator_name: str, rp_id: str, rp_name: str
) -> str:
    """Registration options (excludes the operator's existing credentials) + stash the challenge.
    Runs on ops_readonly (reads existing credential ids)."""
    rows = (
        await session.execute(
            select(OperatorPasskey.credential_id).where(OperatorPasskey.operator_id == operator_id)
        )
    ).all()
    options_json, challenge = webauthn.registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=operator_id.bytes,
        user_name=operator_name,
        exclude_ids=[r[0] for r in rows],
    )
    await webauthn.put_challenge(f"ops_reg:{operator_id}", challenge)
    return options_json


async def passkey_register_finish(
    session: AsyncSession,
    *,
    operator_id: uuid.UUID,
    credential: dict[str, Any],
    rp_id: str,
    origin: str,
    name: str,
) -> None:
    """Verify the attestation and store the credential. Runs on ops_actions (INSERT)."""
    challenge = await webauthn.pop_challenge(f"ops_reg:{operator_id}")
    if challenge is None:
        raise ProblemException(
            slug="passkey_challenge_expired", title="Challenge abgelaufen", status=400
        )
    try:
        reg = webauthn.verify_registration(
            credential=credential, challenge=challenge, rp_id=rp_id, origin=origin
        )
    except Exception as exc:  # any verification failure -> fail closed
        raise ProblemException(
            slug="passkey_invalid", title="Passkey ungültig", status=400
        ) from exc
    session.add(
        OperatorPasskey(
            operator_id=operator_id,
            credential_id=reg.credential_id,
            public_key=reg.public_key,
            sign_count=reg.sign_count,
            name=name,
            transports=reg.transports,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ProblemException(
            slug="passkey_exists", title="Passkey bereits registriert", status=409
        ) from exc


async def passkey_auth_begin(*, rp_id: str) -> tuple[str, str]:
    """Passwordless (discoverable-credential) options; returns (options_json, flow_id). The flow_id
    keys the challenge in Redis and is returned to the client (no cookie)."""
    options_json, challenge = webauthn.authentication_options(rp_id=rp_id, allow_ids=[])
    flow_id = new_token()
    await webauthn.put_challenge(f"ops_auth:{flow_id}", challenge)
    return options_json, flow_id


async def passkey_auth_finish(
    session: AsyncSession, *, credential: dict[str, Any], flow_id: str, rp_id: str, origin: str
) -> Operator:
    """Verify an assertion, bump the sign count, return the authenticated (active) operator. Runs on
    ops_actions (cross-operator credential lookup + sign_count UPDATE). Fails closed."""
    challenge = await webauthn.pop_challenge(f"ops_auth:{flow_id}")
    if challenge is None:
        raise ProblemException(
            slug="passkey_challenge_expired", title="Challenge abgelaufen", status=400
        )
    raw_id = credential.get("id") or credential.get("rawId")
    if not isinstance(raw_id, str):
        raise ProblemException(slug="passkey_invalid", title="Passkey ungültig", status=400)
    # A malformed (non-base64url) id must fail closed as a 400, not leak an unhandled 500.
    try:
        cred_id = webauthn.canonical_id(raw_id)
    except ValueError as exc:  # binascii.Error is a ValueError subclass
        raise ProblemException(
            slug="passkey_invalid", title="Passkey ungültig", status=400
        ) from exc
    pk = await session.scalar(
        select(OperatorPasskey).where(OperatorPasskey.credential_id == cred_id)
    )
    # Uniform 401 title across unknown-credential / inactive-operator / bad-signature so the failure
    # reason is not an enumeration oracle over the (tiny, privileged) operator set.
    if pk is None:
        raise ProblemException(slug="passkey_invalid", title="Passkey ungültig", status=401)
    operator = await session.get(Operator, pk.operator_id)
    if operator is None or not operator.is_active:
        raise ProblemException(slug="passkey_invalid", title="Passkey ungültig", status=401)
    try:
        new_count = webauthn.verify_authentication(
            credential=credential,
            challenge=challenge,
            rp_id=rp_id,
            origin=origin,
            public_key=pk.public_key,
            sign_count=pk.sign_count,
        )
    except Exception as exc:  # signature / sign-count / origin mismatch -> fail closed
        raise ProblemException(
            slug="passkey_invalid", title="Passkey ungültig", status=401
        ) from exc
    pk.sign_count = new_count
    pk.last_used_at = datetime.now(UTC)
    await session.flush()
    return operator


async def list_operator_passkeys(
    session: AsyncSession, *, operator_id: uuid.UUID
) -> list[OperatorPasskey]:
    """The operator's registered passkeys (oldest first)."""
    rows = await session.scalars(
        select(OperatorPasskey)
        .where(OperatorPasskey.operator_id == operator_id)
        .order_by(OperatorPasskey.created_at)
    )
    return list(rows)


async def delete_operator_passkey(
    session: AsyncSession, *, operator_id: uuid.UUID, passkey_id: uuid.UUID
) -> bool:
    """Delete one of the operator's OWN passkeys. Returns False if unknown or not theirs."""
    pk = await session.get(OperatorPasskey, passkey_id)
    if pk is None or pk.operator_id != operator_id:
        return False
    await session.delete(pk)
    await session.flush()
    return True


async def read_kpis(session: AsyncSession) -> OpsKpis:
    """Read the operator dashboard from the aggregate views only (ADR-0015/0071). ``session`` is an
    ``ops_readonly`` session — it can see these views (security-definer, owned by custode_maint) but
    no fact table. Newest day first."""
    row = (await session.execute(text("SELECT * FROM usage_counters"))).one()
    usage = UsageCounters(
        households=row.households,
        users=row.users,
        adult_members=row.adult_members,
        children=row.children,
    )
    days = (
        await session.execute(
            text("SELECT day, new_households, new_users FROM daily_metrics ORDER BY day DESC")
        )
    ).all()
    daily = [
        DailyMetric(day=d.day, new_households=d.new_households, new_users=d.new_users) for d in days
    ]
    return OpsKpis(usage=usage, daily=daily)


async def create_banner(
    session: AsyncSession, *, operator_id: uuid.UUID, data: BannerCreate
) -> Banner:
    """Create a global banner and write an audit entry — both on the ``ops_actions`` session, one
    unit of work. ``detail`` carries only the level (no PII)."""
    banner = Banner(
        message=data.message,
        level=data.level,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        created_by=operator_id,
    )
    session.add(banner)
    await session.flush()
    await record_audit(
        session,
        actor_type="operator",
        actor_id=operator_id,
        action="banner.created",
        target_type="banner",
        target_id=banner.id,
        detail={"level": data.level},
    )
    return banner


async def list_banners(session: AsyncSession) -> list[Banner]:
    """All banners for the ops console (newest first)."""
    rows = await session.scalars(select(Banner).order_by(Banner.created_at.desc()))
    return list(rows)


async def deactivate_banner(
    session: AsyncSession, *, operator_id: uuid.UUID, banner_id: uuid.UUID
) -> Banner | None:
    """Deactivate a banner (audited). Returns ``None`` if it doesn't exist."""
    banner = await session.get(Banner, banner_id)
    if banner is None:
        return None
    banner.is_active = False
    await record_audit(
        session,
        actor_type="operator",
        actor_id=operator_id,
        action="banner.deactivated",
        target_type="banner",
        target_id=banner.id,
    )
    await session.flush()
    return banner


def _household_metadata(row: object) -> HouseholdMetadata:
    return HouseholdMetadata(
        id=row.id,  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        member_count=row.member_count,  # type: ignore[attr-defined]
        admin_count=row.admin_count,  # type: ignore[attr-defined]
    )


async def search_households(
    session: AsyncSession, *, q: str, limit: int = 50
) -> list[HouseholdMetadata]:
    """Support search over the ``household_metadata`` view (ops_readonly): match name (substring) or
    an exact id; empty ``q`` lists the most recent. Metadata only — never household content."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_HM_COLS} FROM household_metadata "  # noqa: S608 - _HM_COLS is a constant
                "WHERE :q = '' OR name ILIKE '%' || :q || '%' OR id::text = :q "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"q": q, "limit": limit},
        )
    ).all()
    return [_household_metadata(r) for r in rows]


async def get_household_metadata(
    session: AsyncSession, *, household_id: uuid.UUID
) -> HouseholdMetadata | None:
    """One household's metadata (ops_readonly), or ``None`` if unknown."""
    row = (
        await session.execute(
            text(
                f"SELECT {_HM_COLS} FROM household_metadata WHERE id = :id"  # noqa: S608 - constant
            ),
            {"id": str(household_id)},
        )
    ).one_or_none()
    return _household_metadata(row) if row is not None else None


async def list_feedback(
    session: AsyncSession, *, category: str | None = None, limit: int = 100
) -> list[OpsFeedbackEntry]:
    """The operator feedback inbox (view ``ops_feedback``, ops_readonly), newest first, optionally
    filtered by category. Reads only the view — never the ``feedback`` fact table."""
    rows = (
        await session.execute(
            text(
                "SELECT id, household_id, category, message, error_ref, route, diagnostics, "
                "created_at "
                "FROM ops_feedback "
                # CAST gives the (possibly NULL) bind param a concrete type — without it asyncpg
                # cannot infer ``$1`` from ``$1 IS NULL`` alone (AmbiguousParameterError).
                "WHERE CAST(:category AS text) IS NULL OR category = :category "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"category": category, "limit": limit},
        )
    ).all()
    return [
        OpsFeedbackEntry(
            id=r.id,
            household_id=r.household_id,
            category=r.category,
            message=r.message,
            error_ref=r.error_ref,
            route=r.route,
            diagnostics=r.diagnostics,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def list_audit(
    session: AsyncSession, *, action: str | None = None, limit: int = 100
) -> list[AuditLogEntry]:
    """Recent ``audit_log`` records (newest first), optionally filtered by exact ``action``. Reads
    on ``ops_readonly`` (SELECT-only grant, migration 0057); the trail is append-only + PII-free, so
    the read is not itself audited. ``occurred_at DESC`` is index-backed (0057)."""
    stmt = select(AuditEntry).order_by(AuditEntry.occurred_at.desc()).limit(limit)
    if action is not None:
        stmt = stmt.where(AuditEntry.action == action)
    rows = await session.scalars(stmt)
    return [
        AuditLogEntry(
            id=r.id,
            occurred_at=r.occurred_at,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            household_id=r.household_id,
            detail=r.detail_json,
            request_id=r.request_id,
        )
        for r in rows
    ]


async def list_active_banners(session: AsyncSession, *, now: datetime) -> list[Banner]:
    """Banners to display in the app right now: active and within their (optional) time window.
    Runs on the app (``custode_app``) read session."""
    rows = await session.scalars(
        select(Banner)
        .where(
            Banner.is_active.is_(True),
            (Banner.starts_at.is_(None)) | (Banner.starts_at <= now),
            (Banner.ends_at.is_(None)) | (Banner.ends_at > now),
        )
        .order_by(Banner.created_at.desc())
    )
    return list(rows)
