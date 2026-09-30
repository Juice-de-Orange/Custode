"""HTTP layer for the Betreiber-Konsole (`/ops`, ADR-0015). Own auth stack (operator bearer token,
no household context); reads run on an ``ops_readonly`` session. KPI endpoints (aggregate views) +
support/actions follow in S7c/S8. CSRF-free by design: bearer token, no ambient cookie."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request, Response, status

from app.kernel.audit.record import record_audit
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession
from app.kernel.auth.webauthn import rp_from_request
from app.kernel.config.flags import DEFAULT_HOUSEHOLD_FLAGS
from app.kernel.config.global_flags import load_global_flags, set_global_flag
from app.kernel.http.problem import ProblemException
from app.modules.backoffice import service
from app.modules.backoffice.dependencies import (
    CurrentOperator,
    OpsActionsSession,
    OpsSession,
    bearer_token,
)
from app.modules.backoffice.models import Banner, Operator
from app.modules.backoffice.schemas import (
    AuditLogEntry,
    BannerCreate,
    BannerLevel,
    BannerResponse,
    FlagSet,
    HouseholdMetadata,
    OperatorLogin,
    OperatorMe,
    OperatorPasskeySummary,
    OperatorSession,
    OperatorSummary,
    OpsFeedbackEntry,
    OpsFlags,
    OpsHealth,
    OpsKpis,
    OpsPasskeyLoginComplete,
    OpsPasskeyLoginOptions,
    OpsPasskeyOptions,
    OpsPasskeyRegisterComplete,
)
from app.modules.backoffice.session import mint_ops_session, revoke_ops_session
from app.settings import get_settings

ops_router = APIRouter(prefix="/ops", tags=["ops"])

# App-facing read of active banners (any signed-in member). Separate from /ops (operator-only).
banners_router = APIRouter(prefix="/v1/banners", tags=["banners"])


def _banner(banner: Banner) -> BannerResponse:
    return BannerResponse(
        id=banner.id,
        message=banner.message,
        level=cast(BannerLevel, banner.level),
        is_active=banner.is_active,
        starts_at=banner.starts_at,
        ends_at=banner.ends_at,
        created_at=banner.created_at,
    )


@ops_router.post("/auth/login")
async def login(payload: OperatorLogin, session: OpsSession) -> OperatorSession:
    """Authenticate an operator (e-mail + password + mandatory TOTP) and mint a bearer session.
    401 on any mismatch (fail-closed, constant-time vs. enumeration)."""
    operator = await service.authenticate_operator(
        session, email=payload.email, password=payload.password, totp_code=payload.totp_code
    )
    if operator is None:
        raise ProblemException(
            slug="invalid_credentials", title="Anmeldung fehlgeschlagen", status=401
        )
    token = await mint_ops_session(operator.id)
    return OperatorSession(token=token)


@ops_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    """Revoke the presented operator session. Idempotent (204 even if the token is unknown)."""
    token = bearer_token(request)
    if token is not None:
        await revoke_ops_session(token)


@ops_router.get("/me")
async def me(operator: CurrentOperator) -> OperatorMe:
    """The authenticated operator."""
    return OperatorMe(id=operator.id, email=operator.email)


@ops_router.get("/health")
async def health(operator: CurrentOperator, response: Response) -> OpsHealth:
    """Build/health info for the ops console (§12). Operator-only."""
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return OpsHealth(env=settings.env, app_version=settings.app_version, git_sha=settings.git_sha)


@ops_router.get("/kpis")
async def kpis(operator: CurrentOperator, session: OpsSession) -> OpsKpis:
    """Operator dashboard: global counters + signup curve, from the aggregate views only (never a
    fact table — ADR-0015/0071). ``operator`` enforces auth; ``session`` runs as ops_readonly."""
    return await service.read_kpis(session)


@ops_router.get("/banners")
async def list_banners(operator: CurrentOperator, session: OpsSession) -> list[BannerResponse]:
    """All global banners (newest first), for the ops console."""
    return [_banner(b) for b in await service.list_banners(session)]


@ops_router.post("/banners", status_code=status.HTTP_201_CREATED)
async def create_banner(
    payload: BannerCreate, operator: CurrentOperator, session: OpsActionsSession
) -> BannerResponse:
    """Create a global banner (audited). Auth via ``operator``; the write runs as ops_actions and is
    recorded in the audit log in the same unit of work."""
    banner = await service.create_banner(session, operator_id=operator.id, data=payload)
    return _banner(banner)


@ops_router.post("/banners/{banner_id}/deactivate")
async def deactivate_banner(
    banner_id: uuid.UUID, operator: CurrentOperator, session: OpsActionsSession
) -> BannerResponse:
    """Deactivate a banner (audited). 404 if it doesn't exist."""
    banner = await service.deactivate_banner(session, operator_id=operator.id, banner_id=banner_id)
    if banner is None:
        raise ProblemException(slug="not_found", title="Banner nicht gefunden", status=404)
    return _banner(banner)


@ops_router.get("/flags")
async def get_flags(operator: CurrentOperator, session: OpsSession) -> OpsFlags:
    """Current global flag overrides + every flaggable key (the console renders all toggles)."""
    return OpsFlags(
        overrides=await load_global_flags(session),
        available=sorted(DEFAULT_HOUSEHOLD_FLAGS),
    )


@ops_router.put("/flags/{key}")
async def set_flag(
    key: str, payload: FlagSet, operator: CurrentOperator, session: OpsActionsSession
) -> OpsFlags:
    """Set a global flag override (audited). 422 if ``key`` is not a flaggable flag."""
    if key not in DEFAULT_HOUSEHOLD_FLAGS:
        raise ProblemException(slug="invalid_flag", title="Unbekanntes Flag", status=422)
    await set_global_flag(session, key=key, enabled=payload.enabled, updated_by=operator.id)
    await record_audit(
        session,
        actor_type="operator",
        actor_id=operator.id,
        action="flag.changed",
        target_type="flag",
        detail={"key": key, "enabled": payload.enabled},
    )
    return OpsFlags(
        overrides=await load_global_flags(session),
        available=sorted(DEFAULT_HOUSEHOLD_FLAGS),
    )


@ops_router.get("/households")
async def search_households(
    operator: CurrentOperator,
    session: OpsSession,
    audit: OpsActionsSession,
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[HouseholdMetadata]:
    """Support search by household name (substring) or exact id — **metadata only** (ADR-0015).
    Empty ``q`` lists the most recent households."""
    # Audited access (ADR-0073): read on ops_readonly, audit record on ops_actions (separate unit of
    # work). The query term is NOT stored — only its length + the result count (no PII).
    term = q.strip()
    results = await service.search_households(session, q=term)
    await record_audit(
        audit,
        actor_type="operator",
        actor_id=operator.id,
        action="household.searched",
        target_type="household",
        detail={"query_length": len(term), "result_count": len(results)},
    )
    return results


@ops_router.get("/households/{household_id}")
async def household_detail(
    household_id: uuid.UUID,
    operator: CurrentOperator,
    session: OpsSession,
    audit: OpsActionsSession,
) -> HouseholdMetadata:
    """One household's metadata (ops_readonly). 404 if unknown."""
    meta = await service.get_household_metadata(session, household_id=household_id)
    if meta is None:
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    # Audited (ADR-0073) only on a successful view — a 404 raised above rolls back the ops_actions
    # session, so nothing-viewed is never recorded.
    await record_audit(
        audit,
        actor_type="operator",
        actor_id=operator.id,
        action="household.viewed",
        target_type="household",
        target_id=household_id,
    )
    return meta


@ops_router.get("/feedback")
async def list_feedback(
    operator: CurrentOperator,
    session: OpsSession,
    audit: OpsActionsSession,
    category: Annotated[str | None, Query(max_length=20)] = None,
) -> list[OpsFeedbackEntry]:
    """The operator feedback inbox (newest first), optionally filtered by category. Reads the
    ``ops_feedback`` view (ops_readonly) — never the feedback fact table (ADR-0015)."""
    # Audited (ADR-0073): category filter + result count only, never message body (no PII).
    results = await service.list_feedback(session, category=category)
    await record_audit(
        audit,
        actor_type="operator",
        actor_id=operator.id,
        action="feedback.inbox.viewed",
        detail={"category": category, "result_count": len(results)},
    )
    return results


@ops_router.get("/audit")
async def list_audit(
    operator: CurrentOperator,
    session: OpsSession,
    action: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AuditLogEntry]:
    """The append-only audit trail (newest first), optionally filtered by exact ``action``. Reads
    ``audit_log`` on ops_readonly (SELECT-only). The trail is PII-free by construction, so — unlike
    the support reads (household/feedback) — viewing it is deliberately NOT itself audited (no
    recursion, no noise)."""
    return await service.list_audit(session, action=action, limit=limit)


def _operator_summary(op: Operator) -> OperatorSummary:
    return OperatorSummary(
        id=op.id,
        email=op.email,
        totp_enabled=op.totp_enabled,
        is_active=op.is_active,
        created_at=op.created_at,
    )


@ops_router.get("/operators")
async def list_operators(operator: CurrentOperator, session: OpsSession) -> list[OperatorSummary]:
    """All operators for management (newest first). Metadata only — never password_hash/totp_secret.
    Provisioning stays CLI/seed (ADR-0015); this UI manages activation, not credentials."""
    return [_operator_summary(o) for o in await service.list_operators(session)]


@ops_router.post("/operators/{operator_id}/deactivate")
async def deactivate_operator(
    operator_id: uuid.UUID, operator: CurrentOperator, session: OpsActionsSession
) -> OperatorSummary:
    """Deactivate an operator (audited). 409 on self-deactivation or on deactivating the last active
    operator (both would risk a console lockout). 404 if unknown."""
    if operator_id == operator.id:
        raise ProblemException(
            slug="cannot_deactivate_self",
            title="Man kann sich nicht selbst deaktivieren",
            status=409,
        )
    try:
        updated = await service.set_operator_active(
            session, operator_id=operator_id, active=False, actor_id=operator.id
        )
    except service.LastActiveOperatorError:
        raise ProblemException(
            slug="cannot_deactivate_last",
            title="Der letzte aktive Operator kann nicht deaktiviert werden",
            status=409,
        ) from None
    if updated is None:
        raise ProblemException(slug="not_found", title="Operator nicht gefunden", status=404)
    return _operator_summary(updated)


@ops_router.post("/operators/{operator_id}/reactivate")
async def reactivate_operator(
    operator_id: uuid.UUID, operator: CurrentOperator, session: OpsActionsSession
) -> OperatorSummary:
    """Reactivate an operator (audited). 404 if unknown."""
    updated = await service.set_operator_active(
        session, operator_id=operator_id, active=True, actor_id=operator.id
    )
    if updated is None:
        raise ProblemException(slug="not_found", title="Operator nicht gefunden", status=404)
    return _operator_summary(updated)


# ---------------------------------------------------------------- operator passkeys (ADR-0072)
# WebAuthn login/enrollment for operators, mirroring the member stack but COOKIELESS: register is
# keyed off the bearer-authenticated operator; passwordless login round-trips an opaque flow_id in
# the body (the ops console has no cookie/CSRF surface — ADR-0015).


@ops_router.post("/auth/passkeys/register/begin")
async def ops_passkey_register_begin(
    operator: CurrentOperator, session: OpsSession, request: Request
) -> OpsPasskeyOptions:
    """Registration options for the logged-in operator to enroll a passkey."""
    rp_id, _origin = rp_from_request(request)
    options_json = await service.passkey_register_begin(
        session,
        operator_id=operator.id,
        operator_name=operator.email,
        rp_id=rp_id,
        rp_name=get_settings().brand_name,
    )
    return OpsPasskeyOptions(options=json.loads(options_json))


@ops_router.post("/auth/passkeys/register/complete", status_code=status.HTTP_204_NO_CONTENT)
async def ops_passkey_register_complete(
    payload: OpsPasskeyRegisterComplete,
    operator: CurrentOperator,
    session: OpsActionsSession,
    request: Request,
) -> None:
    """Verify the attestation and store the operator's new credential (ops_actions)."""
    rp_id, origin = rp_from_request(request)
    await service.passkey_register_finish(
        session,
        operator_id=operator.id,
        credential=payload.credential,
        rp_id=rp_id,
        origin=origin,
        name=payload.name,
    )


@ops_router.post("/auth/passkeys/login/begin")
async def ops_passkey_login_begin(request: Request) -> OpsPasskeyLoginOptions:
    """Passwordless-login options + the cookieless flow_id (echoed back on complete). No auth."""
    rp_id, _origin = rp_from_request(request)
    options_json, flow_id = await service.passkey_auth_begin(rp_id=rp_id)
    return OpsPasskeyLoginOptions(options=json.loads(options_json), flow_id=flow_id)


@ops_router.post("/auth/passkeys/login/complete")
async def ops_passkey_login_complete(
    payload: OpsPasskeyLoginComplete, session: OpsActionsSession, request: Request
) -> OperatorSession:
    """Verify the assertion and mint an operator bearer session (like password+TOTP login). The
    passkey IS the authentication; the write session bumps the credential's sign_count."""
    rp_id, origin = rp_from_request(request)
    operator = await service.passkey_auth_finish(
        session, credential=payload.credential, flow_id=payload.flow_id, rp_id=rp_id, origin=origin
    )
    token = await mint_ops_session(operator.id)
    return OperatorSession(token=token)


@ops_router.get("/passkeys")
async def ops_list_passkeys(
    operator: CurrentOperator, session: OpsSession
) -> list[OperatorPasskeySummary]:
    """The operator's own registered passkeys (no secret material)."""
    items = await service.list_operator_passkeys(session, operator_id=operator.id)
    return [
        OperatorPasskeySummary(
            id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at
        )
        for p in items
    ]


@ops_router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ops_delete_passkey(
    passkey_id: uuid.UUID, operator: CurrentOperator, session: OpsActionsSession
) -> None:
    """Delete one of the operator's own passkeys. 404 if unknown or not theirs."""
    deleted = await service.delete_operator_passkey(
        session, operator_id=operator.id, passkey_id=passkey_id
    )
    if not deleted:
        raise ProblemException(slug="not_found", title="Passkey nicht gefunden", status=404)


@banners_router.get("")
async def active_banners(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[BannerResponse]:
    """Banners to display in the app right now (any signed-in member). Read-only, app role."""
    return [_banner(b) for b in await service.list_active_banners(session, now=datetime.now(UTC))]
