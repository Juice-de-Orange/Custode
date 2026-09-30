"""HTTP layer for ``accounts`` (KONZEPT §5.1, §8). Thin: validate → call services →
translate the ``SessionResult`` into cookies. Opaque cookie sessions (access token in
Redis, rotating refresh in Postgres) with double-submit CSRF. Tokens are never returned
in a body and never logged."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.kernel.auth import access
from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import (
    AdminPrincipal,
    CurrentPrincipal,
    ScopedSession,
)
from app.kernel.auth.webauthn import rp_from_request
from app.kernel.config.flags import get_household_flags
from app.kernel.config.global_flags import load_global_flags
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.cookies import (
    access_cookie_name,
    clear_auth_cookies,
    clear_passkey_flow_cookie,
    passkey_flow_cookie_name,
    refresh_cookie_name,
    set_access_cookie,
    set_csrf_cookie,
    set_passkey_flow_cookie,
    set_refresh_cookie,
)
from app.kernel.http.csrf import new_csrf_token, require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.ports.mail import MailPort, get_mail
from app.modules.accounts import service
from app.modules.accounts.models import Household, Membership, User
from app.modules.accounts.schemas import (
    ChangeRoleRequest,
    ChildLoginRequest,
    ChildResponse,
    CreateChildRequest,
    CreateHouseholdRequest,
    CreateInviteRequest,
    DeletionBlockerResponse,
    DigestSetting,
    DissolveHouseholdRequest,
    DissolvePreview,
    EmailVerifyRequest,
    HouseholdSummary,
    InviteResponse,
    JoinRequest,
    LoginEventResponse,
    LoginRequest,
    MemberResponse,
    MeResponse,
    PasskeyLoginComplete,
    PasskeyOptions,
    PasskeyRegisterComplete,
    PasskeyResponse,
    PasswordForgotRequest,
    PasswordResetRequest,
    ProfileResponse,
    ProfileUpdate,
    RecoveryCodesResponse,
    RegisterRequest,
    SessionResponse,
    SessionView,
    TotpCodeRequest,
    TotpSetupResponse,
)
from app.settings import Settings, get_settings

auth_router = APIRouter(prefix="/v1/auth", tags=["auth"])
account_router = APIRouter(prefix="/v1/account", tags=["account"])


def _client_meta(request: Request) -> tuple[str, str | None, str | None]:
    """(device_label, user_agent, ip) from the request — all best-effort."""
    return (
        request.headers.get("x-device-label", ""),
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )


def _country_code(request: Request, settings: Settings) -> str | None:
    """Two-letter country from the edge header (e.g. CF-IPCountry) for the login audit; None
    if absent. The IP itself is never read into the audit (ADR-0025)."""
    code = request.headers.get(settings.geo_country_header)
    return code.strip().upper()[:2] if code else None


def _issue_session(
    response: Response, settings: Settings, *, access_token: str, refresh_token: str
) -> None:
    """Set all three cookies as a unit. A refresh that forgot to reset the refresh
    cookie would replay the consumed token and trip false theft-detection."""
    set_access_cookie(response, settings, access_token)
    set_refresh_cookie(response, settings, refresh_token)
    set_csrf_cookie(response, settings, new_csrf_token())


async def _default_household(
    user_id: uuid.UUID, family_id: uuid.UUID
) -> tuple[uuid.UUID | None, Role | None]:
    """Household to scope a fresh login to: the user's sole membership, remembered as
    the family's active household (so refresh carries it, like an explicit switch).
    Multi-household users get ``None`` and pick explicitly (P8 Prod-QA finding: a fresh
    login without context 403'd every module screen)."""
    sole = await service.resolve_sole_household(user_id=user_id)
    if sole is None:
        return None, None
    household_id, role = sole
    await access.set_active_household(family_id, household_id, role)
    return household_id, role


def _profile_response(user: User) -> ProfileResponse:
    """Map a user row + its ``settings_json`` blob to the profile contract (defensive coercion)."""
    profile = user.settings_json or {}
    notifications = profile.get("notifications") or {}
    return ProfileResponse(
        display_name=user.display_name,
        locale=user.locale,
        work_hours=str(profile.get("work_hours", "")),
        dietary=[str(x) for x in (profile.get("dietary") or [])],
        notifications={str(k): bool(v) for k, v in dict(notifications).items()},
        version=user.version,
    )


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    mail: Annotated[MailPort, Depends(get_mail)],
) -> SessionResponse:
    user_id = await service.register_user(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        locale=payload.locale,
    )
    device_label, user_agent, ip = _client_meta(request)
    result = await service.login(
        email=payload.email,
        password=payload.password,
        device_label=device_label,
        user_agent=user_agent,
        ip=ip,
        country_code=_country_code(request, get_settings()),
    )
    settings = get_settings()
    access_token = await access.mint_access(
        user_id=result.user_id, household_id=None, role=None, family_id=result.family_id
    )
    _issue_session(
        response, settings, access_token=access_token, refresh_token=result.refresh_token
    )
    await service.send_verification_email(
        user_id=user_id, email=payload.email, mail=mail, base_url=settings.public_base_url
    )
    return SessionResponse(user_id=user_id)


@auth_router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> SessionResponse:
    device_label, user_agent, ip = _client_meta(request)
    result = await service.login(
        email=payload.email,
        password=payload.password,
        totp_code=payload.totp_code,
        recovery_code=payload.recovery_code,
        device_label=device_label,
        user_agent=user_agent,
        ip=ip,
        country_code=_country_code(request, get_settings()),
    )
    settings = get_settings()
    household_id, role = await _default_household(result.user_id, result.family_id)
    access_token = await access.mint_access(
        user_id=result.user_id, household_id=household_id, role=role, family_id=result.family_id
    )
    _issue_session(
        response, settings, access_token=access_token, refresh_token=result.refresh_token
    )
    return SessionResponse(user_id=result.user_id, household_id=household_id, role=role)


@auth_router.post("/child-login")
async def child_login(
    payload: ChildLoginRequest, request: Request, response: Response
) -> SessionResponse:
    # Pre-auth like /login (no CSRF). The child lands directly in their household: the access token
    # is minted scoped to it + role=child, and it is remembered as the family's active household.
    device_label, user_agent, ip = _client_meta(request)
    result, household_id, role = await service.child_login(
        household_id=payload.household_id,
        username=payload.username,
        pin=payload.pin,
        device_label=device_label,
        user_agent=user_agent,
        ip=ip,
    )
    settings = get_settings()
    await access.set_active_household(result.family_id, household_id, role)
    access_token = await access.mint_access(
        user_id=result.user_id, household_id=household_id, role=role, family_id=result.family_id
    )
    _issue_session(
        response, settings, access_token=access_token, refresh_token=result.refresh_token
    )
    return SessionResponse(user_id=result.user_id, household_id=household_id, role=role)


@auth_router.post("/refresh", dependencies=[Depends(require_csrf)])
async def refresh(request: Request, response: Response) -> SessionResponse:
    settings = get_settings()
    refresh_token = request.cookies.get(refresh_cookie_name())
    if not refresh_token:
        raise ProblemException(slug="invalid_token", title="Sitzung ungültig", status=401)
    old_access = request.cookies.get(access_cookie_name(settings))
    try:
        result = await service.refresh(
            refresh_token=refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except service.TokenReuseError as exc:
        # Theft: the service revoked the refresh family in the DB. Burn the family's
        # access tokens in Redis too — keyed by the token's family (from the exception),
        # not the caller's cookie — so an attacker replaying only the stolen refresh token
        # still kills the victim's still-live access token instantly. Then clear cookies.
        await access.revoke_access_family(exc.family_id)
        clear_auth_cookies(response, settings)
        raise
    if old_access:
        await access.revoke_access(old_access)
    # Der gemerkte Haushalt ist ein Hinweis, keine Berechtigung: gültig ist, was die Datenbank
    # jetzt sagt (11-S1g, Begründung in `service.resolve_refresh_scope`). Ohne diese Zeile
    # rotierte eine Sitzung bis zu 30 Tage mit einem Scope weiter, den ein Austritt, eine
    # Haushaltsauflösung oder eine Herabstufung längst entzogen hatte.
    cached = await access.get_active_household(result.family_id)
    scope = await service.resolve_refresh_scope(user_id=result.user_id, cached=cached)
    if cached is not None and scope is None:
        # Räumen NUR, wenn die Datenbank die zwischengespeicherte Zuordnung ausdrücklich abgelehnt
        # hat — sonst fragt jede weitere Rotation dieselbe tote Zuordnung ab und `/me` und Redis
        # behaupten Verschiedenes.
        #
        # Die `cached is not None`-Bedingung ist kein Feinschliff, sondern der Unterschied zwischen
        # einer Aufräumaktion und einem Datenverlust: `get_active_household` ist fail-closed und
        # liefert bei einem Redis-Lesefehler ebenfalls `None` (`kernel/auth/access.py`). Ohne die
        # Bedingung genügte **ein einziger** Aussetzer, um einen gültigen Haushalts-Scope
        # **dauerhaft** zu löschen — aus einer vorübergehenden Störung würde eine bleibende.
        await access.set_active_household(result.family_id, None, None)
    household_id = scope[0] if scope else None
    role = scope[1] if scope else None
    access_token = await access.mint_access(
        user_id=result.user_id, household_id=household_id, role=role, family_id=result.family_id
    )
    _issue_session(
        response, settings, access_token=access_token, refresh_token=result.refresh_token
    )
    return SessionResponse(user_id=result.user_id, household_id=household_id, role=role)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    # CSRF-exempt: idempotent + low-severity, and SameSite=Lax already blocks a
    # cross-site POST from carrying the session cookies. A no-session logout still 204s.
    settings = get_settings()
    # Eine Funktion, nicht zwei Zweige: bis 11-B3 hingen Sitzungs-Widerruf (Postgres) und
    # Token-Entwertung (Redis) an zwei verschiedenen Cookies, und fehlte eines, lief nur die halbe
    # Abmeldung. Begründung und Reihenfolge stehen in ``service.logout``.
    await service.logout(
        refresh_token=request.cookies.get(refresh_cookie_name()),
        access_token=request.cookies.get(access_cookie_name(settings)),
    )
    clear_auth_cookies(response, settings)


@auth_router.get("/me")
async def me(principal: CurrentPrincipal, session: ScopedSession) -> MeResponse:
    user = await session.get(User, principal.user_id)
    if user is None:  # pragma: no cover - a valid principal implies an existing user
        raise ProblemException(slug="unauthorized", title="Nicht angemeldet", status=401)
    remaining = await service.count_recovery_codes(session, user_id=principal.user_id)
    household = (
        await session.get(Household, principal.household_id)
        if principal.household_id is not None
        else None
    )
    settings_json = household.settings_json if household is not None else None
    # Global flag layer = env config overlaid by operator-set runtime overrides (P8-S8c).
    global_flags = {**get_settings().feature_flags, **await load_global_flags(session)}
    flags = get_household_flags(settings_json, global_flags=global_flags)
    return MeResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        household_id=principal.household_id,
        role=principal.role,
        totp_enabled=user.totp_enabled,
        recovery_codes_remaining=remaining,
        email_verified=user.email_verified_at is not None,
        flags=flags,
    )


@auth_router.post("/password/forgot", status_code=status.HTTP_204_NO_CONTENT)
async def password_forgot(
    payload: PasswordForgotRequest, mail: Annotated[MailPort, Depends(get_mail)]
) -> None:
    # Always 204 whether or not the e-mail exists (no enumeration). Pre-auth -> no CSRF.
    await service.request_password_reset(
        email=payload.email, mail=mail, base_url=get_settings().public_base_url
    )


@auth_router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset(payload: PasswordResetRequest) -> None:
    # Authenticated by the reset token (from the e-mail link), not a session -> no CSRF.
    await service.reset_password(token=payload.token, new_password=payload.password)


@auth_router.post(
    "/email/verify/request",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def email_verify_request(
    principal: CurrentPrincipal,
    session: ScopedSession,
    mail: Annotated[MailPort, Depends(get_mail)],
) -> None:
    # Resend the verification e-mail for the logged-in user (no-op if already verified).
    await service.request_email_verification(
        session, user_id=principal.user_id, mail=mail, base_url=get_settings().public_base_url
    )


@auth_router.post("/email/verify/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def email_verify_confirm(payload: EmailVerifyRequest) -> None:
    # Authenticated by the verification token (from the e-mail link), not a session -> no CSRF.
    await service.confirm_email(token=payload.token)


@account_router.get("/profile")
async def get_account_profile(
    principal: CurrentPrincipal, session: ScopedSession, response: Response
) -> ProfileResponse:
    user = await service.get_profile(session, user_id=principal.user_id)
    response.headers["ETag"] = f'"{user.version}"'  # the client echoes this as If-Match on PATCH
    return _profile_response(user)


@account_router.patch("/profile", dependencies=[Depends(require_csrf)])
async def patch_account_profile(
    payload: ProfileUpdate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    session: ScopedSession,
) -> ProfileResponse:
    expected = parse_if_match(request.headers.get("if-match"))
    user = await service.update_profile(
        session, user_id=principal.user_id, expected_version=expected, update=payload
    )
    response.headers["ETag"] = f'"{user.version}"'
    return _profile_response(user)


@auth_router.post("/totp/setup", dependencies=[Depends(require_csrf)])
async def totp_setup(principal: CurrentPrincipal, session: ScopedSession) -> TotpSetupResponse:
    secret, uri = await service.totp_begin_setup(session, user_id=principal.user_id)
    return TotpSetupResponse(secret=secret, otpauth_uri=uri)


@auth_router.post("/totp/enable", dependencies=[Depends(require_csrf)])
async def totp_enable(
    payload: TotpCodeRequest, principal: CurrentPrincipal, session: ScopedSession
) -> RecoveryCodesResponse:
    codes = await service.totp_enable(session, user_id=principal.user_id, code=payload.code)
    return RecoveryCodesResponse(recovery_codes=codes)


@auth_router.post(
    "/totp/disable", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def totp_disable(
    payload: TotpCodeRequest, principal: CurrentPrincipal, session: ScopedSession
) -> None:
    await service.totp_disable(session, user_id=principal.user_id, code=payload.code)


@auth_router.post("/totp/recovery-codes", dependencies=[Depends(require_csrf)])
async def regenerate_recovery_codes(
    principal: CurrentPrincipal, session: ScopedSession
) -> RecoveryCodesResponse:
    user = await session.get(User, principal.user_id)
    if user is None or not user.totp_enabled:
        raise ProblemException(slug="totp_not_enabled", title="2FA ist nicht aktiv", status=409)
    codes = await service.generate_recovery_codes(session, user_id=principal.user_id)
    return RecoveryCodesResponse(recovery_codes=codes)


@auth_router.post("/passkeys/register/begin", dependencies=[Depends(require_csrf)])
async def passkeys_register_begin(
    request: Request, principal: CurrentPrincipal, session: ScopedSession
) -> PasskeyOptions:
    user = await session.get(User, principal.user_id)
    if user is None:  # pragma: no cover - a valid principal implies a user
        raise ProblemException(slug="unauthorized", title="Nicht angemeldet", status=401)
    rp_id, _origin = rp_from_request(request)
    options_json = await service.passkey_register_begin(
        session,
        user_id=principal.user_id,
        user_name=user.email or str(user.id),
        rp_id=rp_id,
        rp_name=get_settings().brand_name,
    )
    return PasskeyOptions(options=json.loads(options_json))


@auth_router.post(
    "/passkeys/register/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def passkeys_register_complete(
    payload: PasskeyRegisterComplete,
    request: Request,
    principal: CurrentPrincipal,
    session: ScopedSession,
) -> None:
    rp_id, origin = rp_from_request(request)
    await service.passkey_register_finish(
        session,
        user_id=principal.user_id,
        credential=payload.credential,
        rp_id=rp_id,
        origin=origin,
        name=payload.name,
    )


@auth_router.post("/passkeys/login/begin")
async def passkeys_login_begin(request: Request, response: Response) -> PasskeyOptions:
    rp_id, _origin = rp_from_request(request)
    options_json, flow_id = await service.passkey_auth_begin(rp_id=rp_id)
    set_passkey_flow_cookie(response, get_settings(), flow_id)
    return PasskeyOptions(options=json.loads(options_json))


@auth_router.post("/passkeys/login/complete")
async def passkeys_login_complete(
    payload: PasskeyLoginComplete, request: Request, response: Response
) -> SessionResponse:
    settings = get_settings()
    flow_id = request.cookies.get(passkey_flow_cookie_name())
    if not flow_id:
        raise ProblemException(
            slug="passkey_challenge_expired", title="Challenge abgelaufen", status=400
        )
    rp_id, origin = rp_from_request(request)
    device_label, user_agent, ip = _client_meta(request)
    result = await service.passkey_auth_finish(
        credential=payload.credential,
        flow_id=flow_id,
        rp_id=rp_id,
        origin=origin,
        device_label=device_label,
        user_agent=user_agent,
        ip=ip,
        country_code=_country_code(request, settings),
    )
    clear_passkey_flow_cookie(response, settings)
    household_id, role = await _default_household(result.user_id, result.family_id)
    access_token = await access.mint_access(
        user_id=result.user_id, household_id=household_id, role=role, family_id=result.family_id
    )
    _issue_session(
        response, settings, access_token=access_token, refresh_token=result.refresh_token
    )
    return SessionResponse(user_id=result.user_id, household_id=household_id, role=role)


@auth_router.get("/passkeys")
async def passkeys_list(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[PasskeyResponse]:
    items = await service.list_passkeys(session, user_id=principal.user_id)
    return [
        PasskeyResponse(id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at)
        for p in items
    ]


@auth_router.delete(
    "/passkeys/{passkey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def passkeys_delete(
    passkey_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> None:
    await service.delete_passkey(session, user_id=principal.user_id, passkey_id=passkey_id)


@auth_router.delete(
    "/account",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_own_account(principal: CurrentPrincipal) -> None:
    """Das eigene Konto zur Löschung vormerken (Art. 17, ADR-0083-Nachbarschaft).

    Sofort gesperrt, nach der Karenz endgültig entfernt. **Jede** Rolle darf das — das Recht
    gehört der Person, nicht ihrem Rang. 409 `last_admin`, wenn sie in einem Haushalt mit weiteren
    Mitgliedern die einzige Person mit Admin-Rechten ist.
    """
    families = await service.request_account_deletion(user_id=principal.user_id)
    # Tokens vor dem Antwortende verbrennen — dieselbe Richtung wie beim Entfernen eines
    # Mitglieds: lieber einmal zu viel ausgeloggt als ein Konto, dessen Löschung läuft und das
    # noch Anfragen beantwortet.
    await service.burn_access_families(families)


@auth_router.get("/account/deletion-blockers")
async def account_deletion_blockers(principal: CurrentPrincipal) -> list[DeletionBlockerResponse]:
    """Was einer Löschung im Weg steht — damit die Oberfläche es **vor** dem Knopfdruck sagen kann
    statt hinterher als Fehler."""
    blockers = await service.account_deletion_blockers(user_id=principal.user_id)
    return [
        DeletionBlockerResponse(household_id=b.household_id, name=b.name, reason=b.reason)
        for b in blockers
    ]


@auth_router.get("/sessions")
async def list_sessions(principal: CurrentPrincipal, session: ScopedSession) -> list[SessionView]:
    """The user's active login sessions/devices (KONZEPT §8: Geräte-Liste). User-scoped (RLS)."""
    items = await service.list_active_sessions(session, user_id=principal.user_id)
    return [
        SessionView(
            family_id=i.family_id,
            device_label=i.device_label,
            user_agent=i.user_agent,
            last_used_at=i.last_used_at,
            current=i.family_id == principal.family_id,
        )
        for i in items
    ]


@auth_router.delete(
    "/sessions/{family_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def revoke_session(
    family_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> None:
    """Remote-logout one session family. Revoke the refresh family in Postgres (user-scoped) and,
    only if that hit a row the user owns, burn its opaque access tokens in Redis — so a foreign or
    stale ``family_id`` is a 404, never a cross-user revoke."""
    revoked = await service.revoke_session(session, user_id=principal.user_id, family_id=family_id)
    if not revoked:
        raise ProblemException(slug="not_found", title="Sitzung nicht gefunden", status=404)
    await access.revoke_access_family(family_id)


@auth_router.get("/login-events")
async def list_login_events(
    principal: CurrentPrincipal, session: ScopedSession
) -> list[LoginEventResponse]:
    """The user's recent login attempts (security activity view). User-scoped (RLS); PII-free."""
    items = await service.list_login_events(session, user_id=principal.user_id)
    return [
        LoginEventResponse(success=i.success, country_code=i.country_code, created_at=i.created_at)
        for i in items
    ]


household_router = APIRouter(prefix="/v1", tags=["households"])


async def _activate_household(
    request: Request,
    response: Response,
    settings: Settings,
    *,
    principal: Principal,
    household_id: uuid.UUID,
    role: Role,
) -> None:
    """Re-mint the access token for ``household_id`` within the same login family and
    remember it as the family's active household (so refresh carries it forward). Only
    the access cookie changes; refresh + csrf stay."""
    old_access = request.cookies.get(access_cookie_name(settings))
    if old_access:
        await access.revoke_access(old_access)
    await access.set_active_household(principal.family_id, household_id, role)
    new_access = await access.mint_access(
        user_id=principal.user_id,
        household_id=household_id,
        role=role,
        family_id=principal.family_id,
    )
    set_access_cookie(response, settings, new_access)


@household_router.post(
    "/households", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_household(
    payload: CreateHouseholdRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> SessionResponse:
    household_id = await service.create_household_with_admin(
        creator_user_id=principal.user_id, name=payload.name
    )
    settings = get_settings()
    await _activate_household(
        request, response, settings, principal=principal, household_id=household_id, role=Role.admin
    )
    return SessionResponse(user_id=principal.user_id, household_id=household_id, role=Role.admin)


@household_router.get("/households")
async def list_households(principal: CurrentPrincipal) -> list[HouseholdSummary]:
    items = await service.list_user_households(user_id=principal.user_id)
    return [
        HouseholdSummary(household_id=i.household_id, name=i.name, role=Role(i.role)) for i in items
    ]


@household_router.post("/households/{household_id}/switch", dependencies=[Depends(require_csrf)])
async def switch_household(
    household_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> SessionResponse:
    role = await service.get_active_role(user_id=principal.user_id, household_id=household_id)
    if role is None:
        raise ProblemException(slug="forbidden", title="Kein Mitglied dieses Haushalts", status=403)
    settings = get_settings()
    await _activate_household(
        request, response, settings, principal=principal, household_id=household_id, role=role
    )
    return SessionResponse(user_id=principal.user_id, household_id=household_id, role=role)


@household_router.post(
    "/households/join", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def join_household(
    payload: JoinRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> SessionResponse:
    household_id, role = await service.accept_invite(user_id=principal.user_id, code=payload.code)
    settings = get_settings()
    await _activate_household(
        request, response, settings, principal=principal, household_id=household_id, role=role
    )
    return SessionResponse(user_id=principal.user_id, household_id=household_id, role=role)


@household_router.post(
    "/household/invites", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_household_invite(
    payload: CreateInviteRequest, session: ScopedSession, principal: AdminPrincipal
) -> InviteResponse:
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    expires_at = datetime.now(UTC) + timedelta(hours=payload.expires_in_hours)
    code = await service.create_invite(
        session,
        household_id=principal.household_id,
        role=payload.role.value,
        expires_at=expires_at,
        max_uses=payload.max_uses,
    )
    return InviteResponse(code=code)


@household_router.get("/household/digest")
async def get_household_digest(session: ScopedSession, principal: AdminPrincipal) -> DigestSetting:
    """Whether the weekly digest is enabled for the active household (admin)."""
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    enabled = await service.get_digest_enabled(session, household_id=principal.household_id)
    return DigestSetting(enabled=enabled)


@household_router.patch("/household/digest", dependencies=[Depends(require_csrf)])
async def patch_household_digest(
    payload: DigestSetting, session: ScopedSession, principal: AdminPrincipal
) -> DigestSetting:
    """Enable/disable the weekly digest for the active household (admin, CSRF)."""
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    enabled = await service.set_digest_enabled(
        session, household_id=principal.household_id, enabled=payload.enabled
    )
    return DigestSetting(enabled=enabled)


@household_router.get("/household/members")
async def list_household_members(session: ScopedSession) -> list[MemberResponse]:
    members = await service.list_members(session)
    return [
        MemberResponse(
            membership_id=m.membership_id,
            user_id=m.user_id,
            role=Role(m.role),
            display_name=m.display_name,
        )
        for m in members
    ]


@household_router.patch(
    "/household/members/{membership_id}",
    dependencies=[Depends(require_csrf)],
)
async def change_member_role(
    membership_id: uuid.UUID,
    payload: ChangeRoleRequest,
    session: ScopedSession,
    principal: AdminPrincipal,
) -> MemberResponse:
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    families = await service.change_role(
        session,
        membership_id=membership_id,
        new_role=payload.role.value,
        household_id=principal.household_id,
    )
    # Nur die Access-Tokens, nicht die Sitzungen: die Person bleibt Mitglied, ihre Rechte ändern
    # sich. Gleiche Reihenfolge und gleiche Begründung wie bei `remove_household_member` — vor dem
    # Commit der Session-Dependency, damit ein Abbruch Richtung WENIGER Rechte fehlt.
    await service.burn_access_tokens(families)
    member = await session.get(Membership, membership_id)
    if member is None:  # pragma: no cover - change_role validated existence
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    user = await session.get(User, member.user_id)
    return MemberResponse(
        membership_id=member.id,
        user_id=member.user_id,
        role=Role(member.role),
        display_name=user.display_name if user is not None else "",
    )


@household_router.delete(
    "/household/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def remove_household_member(
    membership_id: uuid.UUID, session: ScopedSession, principal: AdminPrincipal
) -> None:
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    families = await service.remove_member(
        session, membership_id=membership_id, household_id=principal.household_id
    )
    # Die Redis-Tokens fallen VOR dem Commit (die Session-Dependency committet beim Verlassen —
    # ein eigener Commit hier zerrisse ihre Transaktion). Bewusst diese Richtung: bricht die
    # Transaktion danach ab, ist jemand ausgeloggt, der Mitglied bleibt — er meldet sich neu an.
    # Andersherum bliebe der Zugriff eines entfernten Mitglieds bis zu 15 Minuten offen. Wir
    # fehlen in Richtung WENIGER Zugriff.
    await service.burn_access_families(families)


@household_router.post(
    "/household/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def leave_household(session: ScopedSession, principal: CurrentPrincipal) -> None:
    """Den aktiven Haushalt selbst verlassen (KONZEPT §5.1) — jede Rolle, immer nur die eigene
    Mitgliedschaft. Bis zu diesem Slice konnte nur ein Admin jemanden entfernen; wer selbst gehen
    wollte, musste darum bitten."""
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    families = await service.leave_household(
        session, user_id=principal.user_id, household_id=principal.household_id
    )
    # Gleiche Reihenfolge und gleiche Begründung wie bei `remove_household_member`: die
    # Redis-Tokens fallen VOR dem Commit der Session-Dependency.
    await service.burn_access_families(families)


@household_router.get("/household/dissolve-preview")
async def dissolve_preview(session: ScopedSession, principal: AdminPrincipal) -> DissolvePreview:
    """Was die Auflösung beendet — damit die Oberfläche es VOR dem Knopf sagen kann.

    Bewusst keine Fachzähler (Rezepte, Termine …): die kämen nur über Fremdtabellen, und
    ``modules/accounts`` liest keine (E2). Was zählt, steht ohnehin hier: wie viele Menschen es
    trifft und wie viele Kinder-Konten mit enden.
    """
    if principal.household_id is None:  # pragma: no cover - admin impliziert einen Haushalt
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    household = await session.get(Household, principal.household_id)
    if household is None or household.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    members = await service.list_members(session)
    return DissolvePreview(
        household_name=household.name,
        member_count=len(members),
        child_account_count=sum(1 for m in members if m.role == Role.child.value),
    )


@household_router.post(
    "/household/dissolve",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def dissolve_household(
    payload: DissolveHouseholdRequest, session: ScopedSession, principal: AdminPrincipal
) -> None:
    """Den eigenen Haushalt auflösen (Art. 17, KONZEPT §5.1, ADR-0085).

    Der abgetippte Name ist die Bestätigung — Begründung im Schema. **Keine Blocker:** das hier ist
    die Operation, die ``sole_member`` und ``only_children`` auflöst; symmetrisch welche einzubauen
    wäre ein Zirkel.
    """
    if principal.household_id is None:  # pragma: no cover - admin impliziert einen Haushalt
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    household = await session.get(Household, principal.household_id)
    if household is None:
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    if payload.confirm_name.strip() != household.name.strip():
        raise ProblemException(
            slug="name_mismatch",
            title="Name stimmt nicht",
            status=422,
            detail="Bitte den Haushaltsnamen genau so eingeben, wie er oben steht.",
        )
    families = await service.dissolve_household(
        session, household_id=principal.household_id, actor_id=principal.user_id
    )
    # Gleiche Reihenfolge und Begründung wie beim Entfernen: die Redis-Tokens fallen VOR dem
    # Commit der Session-Dependency. Wir fehlen Richtung weniger Zugriff.
    await service.burn_access_families(families)


@household_router.post(
    "/household/children", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_household_child(
    payload: CreateChildRequest, principal: AdminPrincipal
) -> ChildResponse:
    """Admin creates a child account (username + PIN, no e-mail) with recorded parental consent."""
    if principal.household_id is None:  # pragma: no cover - admin implies an active household
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    child_id = await service.create_child(
        household_id=principal.household_id,
        granted_by=principal.user_id,
        display_name=payload.display_name,
        username=payload.username,
        pin=payload.pin,
    )
    return ChildResponse(
        user_id=child_id, username=payload.username, display_name=payload.display_name
    )
