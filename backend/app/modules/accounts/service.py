"""accounts use-cases. Services own transaction boundaries and are testable
without HTTP. Household creation scopes the session to the new id so RLS passes."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth import access, childpin, totp, webauthn
from app.kernel.auth.context import Role
from app.kernel.auth.login_events import AuthLoginEvent, record_login_event
from app.kernel.auth.passkeys import Passkey
from app.kernel.auth.passwords import hash_password, password_too_weak, verify_password
from app.kernel.auth.pwned import pwned_count
from app.kernel.auth.recovery import RecoveryCode
from app.kernel.auth.reset import consume_reset_token, issue_reset_token
from app.kernel.auth.sessions import AuthSession
from app.kernel.auth.tokens import hash_token, new_token
from app.kernel.auth.verification import consume_verification_token, issue_verification_token
from app.kernel.config.flags import get_household_flags
from app.kernel.config.global_flags import load_global_flags
from app.kernel.db.engine import get_maint_sessionmaker
from app.kernel.db.ids import new_uuid7
from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.ports.mail import MailPort
from app.kernel.tenancy.session import maint_session, scoped_session
from app.modules.accounts.models import Consent, Household, Invite, Membership, User
from app.modules.accounts.schemas import ProfileUpdate
from app.settings import get_settings

_ADMIN = Role.admin.value
_CHILD = Role.child.value


@dataclass(frozen=True)
class SessionResult:
    """Outcome of login/refresh. ``refresh_token`` is clear-text, returned once.
    ``family_id`` is the rotation family — the HTTP layer keys the opaque access
    token to it so a theft-revoke can burn every access token of this login."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    family_id: uuid.UUID
    refresh_token: str
    expires_at: datetime


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    # Verified against on the unknown-user path so login timing doesn't leak whether
    # an e-mail exists (user enumeration).
    return hash_password("constant-time-dummy-never-matches")


def _reject_deleted(user: User | None) -> None:
    """Ein zur Löschung vorgemerktes Konto kommt nicht mehr herein — auf **keinem** Weg.

    Es gibt fünf Türen: Passwort-Login, Kind-PIN, Passkey, Refresh-Rotation und der Weg über einen
    Passwort-Reset. Eine vergessene Tür wäre die ganze Lücke, deshalb steht die Prüfung als eigene
    Funktion da und nicht fünfmal als Zeile: wer eine sechste Tür baut, findet sie beim Lesen der
    Nachbarn.

    Die Antwort ist bewusst dieselbe wie bei falschen Zugangsdaten (401 ``invalid_credentials``).
    Ein eigener Slug verriete einem Fremden, dass es dieses Konto gab und dass es gelöscht wird —
    eine Auskunft, die niemandem zusteht und der löschenden Person schadet.

    ``deleted_at`` ist dabei kein „weg", sondern „gesperrt, Frist läuft": der Reaper räumt die
    Zeile erst nach der Karenz. Bis dahin ist das Konto nicht benutzbar, aber wiederherstellbar.
    """
    if user is not None and user.deleted_at is not None:
        raise ProblemException(
            slug="invalid_credentials", title="E-Mail oder Passwort falsch", status=401
        )


async def login(
    *,
    email: str,
    password: str,
    totp_code: str | None = None,
    recovery_code: str | None = None,
    device_label: str = "",
    user_agent: str | None = None,
    ip: str | None = None,
    country_code: str | None = None,
) -> SessionResult:
    """Authenticate by e-mail + password (+ TOTP if enabled) and start a rotating refresh
    session (KONZEPT §8.5). Always runs one Argon2 verify (constant-time vs. enumeration).
    Raises 401 ``ProblemException`` on bad credentials, or ``totp_required`` when the
    second factor is enabled and missing/wrong. Runs as ``custode_maint``: the user isn't
    scoped yet, so the lookup is cross-user."""
    email_norm = email.strip().lower()
    async with maint_session() as session:
        user = await session.scalar(select(User).where(User.email == email_norm))
        stored = user.password_hash if user and user.password_hash else _dummy_hash()
        password_ok = verify_password(stored, password)
        # Erst nach dem Argon2-Verify prüfen: sonst antwortete ein gelöschtes Konto messbar
        # schneller als ein falsches Passwort und wäre damit von außen unterscheidbar.
        _reject_deleted(user)
        if user is None or user.password_hash is None or not password_ok:
            await record_login_event(
                user_id=user.id if user is not None else None,
                success=False,
                country_code=country_code,
            )
            raise ProblemException(
                slug="invalid_credentials", title="E-Mail oder Passwort falsch", status=401
            )
        if user.totp_enabled:
            ok = bool(totp_code) and totp.verify(user.totp_secret or "", totp_code or "")
            if not ok and recovery_code:
                ok = await consume_recovery_code(session, user_id=user.id, code=recovery_code)
            if not ok:
                # Password was correct; the second factor (TOTP or recovery code) failed.
                await record_login_event(user_id=user.id, success=False, country_code=country_code)
                raise ProblemException(
                    slug="totp_required",
                    title="Zwei-Faktor-Code erforderlich",
                    status=401,
                    detail="Code aus der Authenticator-App oder einen Recovery-Code angeben.",
                )
        refresh_token = new_token()
        family_id = new_uuid7()
        expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl_s)
        sess = AuthSession(
            user_id=user.id,
            family_id=family_id,
            refresh_hash=hash_token(refresh_token),
            device_label=device_label,
            user_agent=user_agent,
            ip=ip,
            expires_at=expires_at,
        )
        session.add(sess)
        await session.flush()
        await record_login_event(user_id=user.id, success=True, country_code=country_code)
        return SessionResult(
            user_id=user.id,
            session_id=sess.id,
            family_id=family_id,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )


class TokenReuseError(ProblemException):
    """Refresh-token reuse (theft signal). Carries the rotation ``family_id`` so the HTTP
    layer can burn the family's opaque access tokens in Redis keyed by the *token's*
    family — not the caller's cookie — so an attacker replaying only the stolen refresh
    token still triggers the instant kill. ``family_id`` is deliberately NOT put in the
    problem ``extra`` (it must not leak into the response body)."""

    def __init__(self, *, family_id: uuid.UUID) -> None:
        super().__init__(
            slug="token_reuse",
            title="Sitzung widerrufen",
            status=401,
            detail="Der Token wurde wiederverwendet — alle Sitzungen dieses Geräts wurden aus "
            "Sicherheitsgründen beendet. Bitte neu anmelden.",
        )
        self.family_id = family_id


async def refresh(
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> SessionResult:
    """Rotate a refresh token (KONZEPT §8.5): the presented token is consumed and a
    fresh one issued in the same family. Re-presenting a consumed (rotated) or revoked
    token is a theft signal — the whole family is revoked and the request refused.
    Runs as ``custode_maint`` (the user is identified by the token, not yet scoped)."""
    token_hash = hash_token(refresh_token)
    # Explicit transaction control (not maint_session): on reuse we must COMMIT the
    # family revocation *before* raising — otherwise the theft response would roll it
    # back and the reuse protection would be a no-op.
    sessionmaker = get_maint_sessionmaker()
    async with sessionmaker() as session:
        sess = await session.scalar(
            select(AuthSession).where(AuthSession.refresh_hash == token_hash)
        )
        if sess is None:
            raise ProblemException(slug="invalid_token", title="Sitzung ungültig", status=401)
        now = datetime.now(UTC)
        if sess.rotated_at is not None or sess.revoked_at is not None:
            # Reuse of a consumed/revoked token -> theft. Burn the whole family and
            # COMMIT before signalling, so the revocation survives the raised error.
            await session.execute(
                update(AuthSession)
                .where(AuthSession.family_id == sess.family_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await session.commit()
            raise TokenReuseError(family_id=sess.family_id)
        if sess.expires_at <= now:
            raise ProblemException(slug="expired_token", title="Sitzung abgelaufen", status=401)

        # Die Sitzung selbst wird beim Löschantrag widerrufen; diese Prüfung ist der Gürtel zum
        # Hosenträger — ein Refresh-Token, das die Widerrufsschleife überlebt hätte (Rennen
        # zwischen Antrag und Rotation), verlängerte sonst den Zugang um dreißig Tage.
        _reject_deleted(await session.get(User, sess.user_id))
        sess.rotated_at = now
        sess.last_used_at = now
        new_refresh = new_token()
        expires_at = now + timedelta(seconds=get_settings().refresh_token_ttl_s)
        fresh = AuthSession(
            user_id=sess.user_id,
            family_id=sess.family_id,
            refresh_hash=hash_token(new_refresh),
            device_label=sess.device_label,
            user_agent=user_agent,
            ip=ip,
            expires_at=expires_at,
        )
        session.add(fresh)
        await session.commit()
        return SessionResult(
            user_id=sess.user_id,
            session_id=fresh.id,
            family_id=sess.family_id,
            refresh_token=new_refresh,
            expires_at=expires_at,
        )


async def logout(*, refresh_token: str | None = None, access_token: str | None = None) -> None:
    """End a session **completely**: the refresh family in Postgres *and* its opaque access tokens
    plus the remembered household in Redis.

    **Warum das eine Funktion ist und nicht zwei Zweige.** Bis 11-B3 hingen die beiden Wirkungen an
    **zwei verschiedenen Cookies** — mit verschiedenen Pfaden (``/`` und ``/v1/auth``) und
    verschiedenen Lebensdauern (15 min und 30 Tage). Fehlte eines, lief nur die halbe Abmeldung,
    und zwar in beide Richtungen:

    * ohne Access-Cookie blieben ``access_family:<fam>`` und ``active_household:<fam>`` stehen,
      während die Sitzung in Postgres widerrufen wurde;
    * ohne Refresh-Cookie wurde Redis verbrannt und ``revoked_at`` blieb **NULL** — die Sitzung
      lebte weiter und liess sich mit dem Refresh-Token jederzeit zurückholen. Das ist der
      ernstere der beiden.

    Die Familie ist die stabile Klammer zwischen beiden Speichern; sie wird deshalb aus dem
    genommen, was da ist — vorzugsweise aus dem Refresh-Token (Nachschlag in der Datenbank, auch
    für ein bereits rotiertes Token), sonst aus den Access-Claims. ``/v1/auth/sessions/{family_id}``
    macht daneben genau dasselbe **unbedingt**; dort ist die Familie ein Parameter statt eine
    Ableitung aus einem Cookie.

    **Reihenfolge:** erst Postgres, dann Redis. Der dauerhafte Widerruf landet zuerst; scheitert
    danach Redis, lebt höchstens noch ein Access-Token bis zum Ablauf seiner 15 Minuten und kann
    nicht erneuert werden. Andersherum wäre die Sitzung mit dem Refresh-Cookie zurückholbar — wir
    fehlen Richtung **weniger** Zugriff.

    Idempotent und ohne Enumeration: unbekannte oder bereits widerrufene Token sind ein stiller
    No-Op.
    """
    claims = await access.load_access(access_token) if access_token else None
    family_id = claims.family_id if claims is not None else None

    if refresh_token is not None:
        token_hash = hash_token(refresh_token)
        async with maint_session() as session:
            sess = await session.scalar(
                select(AuthSession).where(AuthSession.refresh_hash == token_hash)
            )
            if sess is not None:
                family_id = sess.family_id

    if family_id is None:
        # Kein auflösbares Token. Ein *fehlerhafter* Redis-Eintrag ist der einzige Fall, in dem
        # ``load_access`` ``None`` liefert und der Schlüssel trotzdem existiert — den räumen wir
        # weg, statt ihn seine Restlaufzeit absitzen zu lassen.
        if access_token:
            await access.revoke_access(access_token)
        return

    async with maint_session() as session:
        await session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await access.revoke_access_family(family_id)


@dataclass(frozen=True)
class ActiveSession:
    """One live login/device — the non-rotated, non-revoked, unexpired token of a family."""

    family_id: uuid.UUID
    device_label: str
    user_agent: str | None
    last_used_at: datetime


async def list_active_sessions(session: AsyncSession, *, user_id: uuid.UUID) -> list[ActiveSession]:
    """A user's live refresh sessions — one per rotation family (the current token: not rotated,
    not revoked, unexpired). Runs under the user-scoped session (RLS ``user_id = app.user_id``);
    the explicit ``user_id`` filter keeps it correct under maint too. Deduped by family (defensive
    against any momentary double-live row)."""
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.rotated_at.is_(None),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.last_used_at.desc())
    )
    seen: set[uuid.UUID] = set()
    out: list[ActiveSession] = []
    for sess in rows:
        if sess.family_id in seen:
            continue
        seen.add(sess.family_id)
        out.append(
            ActiveSession(
                family_id=sess.family_id,
                device_label=sess.device_label,
                user_agent=sess.user_agent,
                last_used_at=sess.last_used_at,
            )
        )
    return out


async def revoke_all_sessions(*, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Revoke every live login session of a user and return their family ids.

    Vier Aufrufer: Passwort-Reset, Kontolöschung, Selbst-Austritt — und das **Entfernen durch
    einen Admin**. Bei den ersten dreien ist die betroffene Person die aufrufende; beim vierten
    nicht, und genau daran ist die erste Fassung gescheitert (BUGLOG 2026-08-01).

    **Warum das eine eigene ``maint``-Session braucht.** ``auth_sessions`` trägt
    ``FORCE ROW LEVEL SECURITY`` mit dem Prädikat ``user_id = current_setting('app.user_id')``
    (Migration 0005). Nahm die Funktion die Session des Aufrufers entgegen, passte das Prädikat
    zufällig in drei von vier Fällen — und traf im vierten **null Zeilen**, still und ohne Fehler.
    Ein entferntes Mitglied behielt sein Access-Token (bis zu 15 min) *und* seine Refresh-Familie:
    ``Principal`` wird aus dem opaken Token gebaut, nie je Anfrage gegen die Datenbank geprüft, und
    ``refresh`` holt den Haushalts-Scope aus Redis. Der Zugriff überlebte damit rollierend, nicht
    für Minuten. Die Signatur nimmt deshalb **keine Session mehr entgegen** — die Falle ist
    entfernt, nicht an einer Stelle umgangen.

    **Die eigene Transaktion committet vor der des Aufrufers**, und das ist die richtige Richtung:
    bricht der Aufrufer danach ab, ist jemand ausgeloggt, der Mitglied bleibt — er meldet sich neu
    an. Andersherum bliebe der Zugriff offen. Wir fehlen Richtung **weniger** Zugriff.

    Das Verbrennen der Redis-Tokens gehört weiterhin zum Aufrufer (``burn_access_families``).
    """
    async with maint_session() as session:
        rows = await session.scalars(
            select(AuthSession.family_id).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
        families = set(rows)
        if families:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
    return families


async def live_session_families(*, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Die Familien der lebenden Sitzungen einer Person — **ohne** sie zu widerrufen.

    Für Vorgänge, die die Rechte ändern, aber nicht den Zugang: nach einem Rollenwechsel bleibt
    die Sitzung gültig, nur ihr Access-Token trägt eine überholte Rolle.

    Öffnet aus demselben Grund wie ``revoke_all_sessions`` eine eigene ``maint``-Session und nimmt
    **keine** entgegen: ``auth_sessions`` filtert per RLS auf ``user_id = app.user_id``. Auf der
    Session des aufrufenden Admins lieferte diese Abfrage die Zeilen der betroffenen Person
    **nicht** — sie käme leer zurück, ohne Fehler, und der Rollenwechsel bliebe wirkungslos. Genau
    diese Falle steckte in der ersten Fassung von ``revoke_all_sessions`` (BUGLOG 2026-08-01).
    """
    async with maint_session() as session:
        rows = await session.scalars(
            select(AuthSession.family_id).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
        return set(rows)


async def burn_access_families(families: set[uuid.UUID]) -> None:
    """Drop the opaque access tokens of these session families from Redis — nach dem Commit."""
    for family_id in families:
        await access.revoke_access_family(family_id)


async def burn_access_tokens(families: set[uuid.UUID]) -> None:
    """Nur die Access-Tokens dieser Familien entwerten; Sitzung und gemerkter Haushalt bleiben.

    Gegenstück zu ``burn_access_families`` für Rechte- statt Zugangsänderungen — Begründung in
    ``kernel/auth/access.revoke_access_tokens``."""
    for family_id in families:
        await access.revoke_access_tokens(family_id)


async def revoke_session(
    session: AsyncSession, *, user_id: uuid.UUID, family_id: uuid.UUID
) -> bool:
    """Revoke an entire session family the user owns (remote logout). Returns ``True`` when it
    revoked an active family — the caller then burns that family's Redis access tokens. RLS plus
    the explicit ``user_id`` guard make a foreign/guessed ``family_id`` a no-op (``False`` → 404),
    so a user can never revoke another user's session or burn their access tokens."""
    result = await session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.family_id == family_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(AuthSession.id)
    )
    return len(result.scalars().all()) > 0


async def list_login_events(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
) -> list[AuthLoginEvent]:
    """A user's recent login attempts (newest first) for the security activity view. Runs under
    the user-scoped session (RLS ``user_id = app.user_id``); rows are PII-free (country code only),
    NULL-user rows (unknown e-mail) stay maint-only and never surface here."""
    rows = await session.scalars(
        select(AuthLoginEvent)
        .where(AuthLoginEvent.user_id == user_id)
        .order_by(AuthLoginEvent.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def request_password_reset(*, email: str, mail: MailPort, base_url: str) -> None:
    """Start a password reset: if the e-mail belongs to a user, mail a single-use 1-hour reset
    link. Always returns ``None`` and never reveals whether the address exists (no enumeration).
    Looks up the user as maint (pre-tenant, by e-mail); the e-mail send is best-effort."""
    email_norm = email.strip().lower()
    async with maint_session() as session:
        user = await session.scalar(select(User).where(User.email == email_norm))
    if user is None:
        return  # identical outcome to the found case — no enumeration
    token = await issue_reset_token(user.id)
    link = f"{base_url.rstrip('/')}/reset-password?token={token}"
    body = (
        "Hallo,\n\n"
        "zum Zurücksetzen deines Passworts öffne diesen Link (eine Stunde gültig):\n\n"
        f"{link}\n\n"
        "Wenn du das nicht angefordert hast, kannst du diese E-Mail ignorieren.\n"
    )
    await mail.send(to=email_norm, subject="Passwort zurücksetzen", body_md=body)


async def reset_password(*, token: str, new_password: str) -> None:
    """Complete a password reset: validate the new password, then consume the token, set the new
    Argon2id hash, and revoke ALL of the user's sessions (a reset implies the old credentials may
    be compromised). Validating *before* consuming means a rejected weak/breached password does
    not burn the link. The update runs self-scoped (``users`` WITH CHECK ``id = app.user_id``)."""
    reason = password_too_weak(new_password)
    if reason is not None:
        raise ProblemException(
            slug="weak_password", title="Passwort zu schwach", status=422, detail=reason
        )
    if await pwned_count(new_password):
        raise ProblemException(
            slug="pwned_password",
            title="Passwort aus Datenleck",
            status=422,
            detail="Dieses Passwort taucht in bekannten Datenlecks auf. Bitte ein anderes wählen.",
        )
    user_id = await consume_reset_token(token)
    if user_id is None:
        raise ProblemException(
            slug="reset_invalid", title="Link ungültig oder abgelaufen", status=400
        )
    async with scoped_session(household_id=user_id, user_id=user_id) as session:
        user = await session.get(User, user_id)
        if user is None:  # account vanished between request and reset
            raise ProblemException(slug="reset_invalid", title="Link ungültig", status=400)
        if user.deleted_at is not None:
            # Ein Reset-Link ist 24 h gültig — lange genug, um die Löschung zu überholen.
            raise ProblemException(slug="reset_invalid", title="Link ungültig", status=400)
        user.password_hash = hash_password(new_password)
        families = await revoke_all_sessions(user_id=user_id)
    await burn_access_families(families)


async def send_verification_email(
    *, user_id: uuid.UUID, email: str, mail: MailPort, base_url: str
) -> None:
    """Mail a single-use 24-hour e-mail-verification link. Best-effort (a mail failure is a no-op;
    the user can resend)."""
    token = await issue_verification_token(user_id)
    link = f"{base_url.rstrip('/')}/verify-email?token={token}"
    body = (
        "Hallo,\n\n"
        "bitte bestätige deine E-Mail-Adresse über diesen Link (24 Stunden gültig):\n\n"
        f"{link}\n\n"
        "Wenn du kein Konto angelegt hast, kannst du diese E-Mail ignorieren.\n"
    )
    await mail.send(to=email, subject="E-Mail bestätigen", body_md=body)


async def request_email_verification(
    session: AsyncSession, *, user_id: uuid.UUID, mail: MailPort, base_url: str
) -> None:
    """Resend the verification e-mail for the current user (no-op if there is no e-mail or it is
    already verified). Reads the user's own row via the request's self-scoped session."""
    user = await session.get(User, user_id)
    if user is None or user.email is None or user.email_verified_at is not None:
        return
    await send_verification_email(user_id=user_id, email=user.email, mail=mail, base_url=base_url)


async def confirm_email(*, token: str) -> None:
    """Confirm an e-mail address from a verification token. A valid token stamps
    ``email_verified_at`` (self-scoped update); an unknown/expired token is a 400."""
    user_id = await consume_verification_token(token)
    if user_id is None:
        raise ProblemException(
            slug="verify_invalid", title="Link ungültig oder abgelaufen", status=400
        )
    async with scoped_session(household_id=user_id, user_id=user_id) as session:
        user = await session.get(User, user_id)
        if user is None:
            raise ProblemException(slug="verify_invalid", title="Link ungültig", status=400)
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)


async def get_profile(session: AsyncSession, *, user_id: uuid.UUID) -> User:
    """Load the user's own row for the profile view (self-scoped session)."""
    user = await session.get(User, user_id)
    if user is None:  # pragma: no cover - a valid principal implies a user
        raise ProblemException(slug="not_found", title="Konto nicht gefunden", status=404)
    return user


async def update_profile(
    session: AsyncSession, *, user_id: uuid.UUID, expected_version: int, update: ProfileUpdate
) -> User:
    """Patch the user's own profile under optimistic concurrency: ``expected_version`` (the
    caller's If-Match) must equal the current ``version`` or the write is refused (412). The shared
    ``set_updated_and_version`` trigger bumps ``version`` on write; flush+refresh so the response
    carries the new ETag. Self-scoped (``users`` WITH CHECK ``id = app.user_id``)."""
    user = await session.get(User, user_id)
    if user is None:  # pragma: no cover - a valid principal implies a user
        raise ProblemException(slug="not_found", title="Konto nicht gefunden", status=404)
    if user.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Profil zwischenzeitlich geändert", status=412
        )
    if update.display_name is not None:
        user.display_name = update.display_name
    if update.locale is not None:
        user.locale = update.locale
    profile = dict(user.settings_json)
    if update.work_hours is not None:
        profile["work_hours"] = update.work_hours
    if update.dietary is not None:
        profile["dietary"] = update.dietary
    if update.notifications is not None:
        profile["notifications"] = update.notifications
    user.settings_json = profile  # reassign so SQLAlchemy detects the JSONB change
    await session.flush()
    await session.refresh(user, attribute_names=["version", "updated_at"])
    return user


async def register_user(
    *,
    email: str,
    password: str,
    display_name: str,
    locale: str = "de",
    pwned_client: httpx.AsyncClient | None = None,
) -> uuid.UUID:
    """Register a new global identity (KONZEPT §5.1). Enforces the password policy
    and the HIBP pwned-check *before* touching the DB, Argon2id-hashes, and inserts
    via the self-scoped bootstrap path (``users`` WITH CHECK ``id = app.user_id``).
    Raises ``ProblemException`` on a weak/breached password or a taken e-mail."""
    reason = password_too_weak(password)
    if reason is not None:
        raise ProblemException(
            slug="weak_password", title="Passwort zu schwach", status=422, detail=reason
        )
    # None => HIBP unreachable; proceed (Null-Adapter). >0 => breached; reject.
    if await pwned_count(password, client=pwned_client):
        raise ProblemException(
            slug="pwned_password",
            title="Passwort aus Datenleck",
            status=422,
            detail="Dieses Passwort taucht in bekannten Datenlecks auf. Bitte ein anderes wählen.",
        )

    user_id = new_uuid7()
    password_hash = hash_password(password)
    # Self-scope to the new id so the users WITH CHECK passes without a household.
    async with scoped_session(household_id=user_id, user_id=user_id) as session:
        session.add(
            User(
                id=user_id,
                email=email.strip().lower(),
                password_hash=password_hash,
                display_name=display_name,
                locale=locale,
            )
        )
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ProblemException(
                slug="email_taken", title="E-Mail bereits vergeben", status=409
            ) from exc
    return user_id


async def totp_begin_setup(session: AsyncSession, *, user_id: uuid.UUID) -> tuple[str, str]:
    """Generate a *pending* TOTP secret for the user (not yet enabled) and return it +
    the otpauth URI. Enabling needs a confirming code via ``totp_enable``. Runs on the
    user's own row (the request's self-scoped session)."""
    user = await session.get(User, user_id)
    if user is None:
        raise ProblemException(slug="not_found", title="Konto nicht gefunden", status=404)
    if user.totp_enabled:
        raise ProblemException(
            slug="totp_already_enabled", title="2FA ist bereits aktiv", status=409
        )
    secret = totp.generate_secret()
    user.totp_secret = secret
    uri = totp.provisioning_uri(
        secret, account=user.email or str(user.id), issuer=get_settings().brand_name
    )
    return secret, uri


async def totp_enable(session: AsyncSession, *, user_id: uuid.UUID, code: str) -> list[str]:
    """Confirm setup: verify ``code`` against the pending secret, enable TOTP, and return
    a fresh set of one-time recovery codes (shown to the user once)."""
    user = await session.get(User, user_id)
    if user is None or user.totp_secret is None:
        raise ProblemException(slug="totp_not_set_up", title="Kein 2FA-Setup vorhanden", status=409)
    if user.totp_enabled:
        raise ProblemException(
            slug="totp_already_enabled", title="2FA ist bereits aktiv", status=409
        )
    if not totp.verify(user.totp_secret, code):
        raise ProblemException(slug="totp_invalid", title="Code ungültig", status=422)
    user.totp_enabled = True
    return await generate_recovery_codes(session, user_id=user_id)


async def totp_disable(session: AsyncSession, *, user_id: uuid.UUID, code: str) -> None:
    """Disable TOTP after verifying a current code (proves possession of the device)."""
    user = await session.get(User, user_id)
    if user is None or not user.totp_enabled or user.totp_secret is None:
        raise ProblemException(slug="totp_not_enabled", title="2FA ist nicht aktiv", status=409)
    if not totp.verify(user.totp_secret, code):
        raise ProblemException(slug="totp_invalid", title="Code ungültig", status=422)
    user.totp_secret = None
    user.totp_enabled = False
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))


def _new_recovery_code() -> str:
    return secrets.token_hex(8)  # 16 hex chars, 64-bit — manually enterable


async def generate_recovery_codes(
    session: AsyncSession, *, user_id: uuid.UUID, count: int = 10
) -> list[str]:
    """Replace the user's recovery codes with a fresh set and return the plaintext once
    (stored only as SHA-256 hashes). Used by ``totp_enable`` and the regenerate route."""
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = [_new_recovery_code() for _ in range(count)]
    session.add_all(RecoveryCode(user_id=user_id, code_hash=hash_token(code)) for code in codes)
    await session.flush()
    return codes


async def consume_recovery_code(session: AsyncSession, *, user_id: uuid.UUID, code: str) -> bool:
    """Single-use: atomically mark a matching *unused* code used. True if one was consumed.
    Runs in the login maint-session (cross-user, before the user is scoped)."""
    result = await session.execute(
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == user_id,
            RecoveryCode.code_hash == hash_token(code),
            RecoveryCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
        .returning(RecoveryCode.id)
    )
    return result.first() is not None


async def count_recovery_codes(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """How many unused recovery codes the user has left."""
    total = await session.scalar(
        select(func.count())
        .select_from(RecoveryCode)
        .where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
    )
    return total or 0


@dataclass(frozen=True)
class PasskeyInfo:
    """A registered passkey for the management list (no secret material)."""

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


async def passkey_register_begin(
    session: AsyncSession, *, user_id: uuid.UUID, user_name: str, rp_id: str, rp_name: str
) -> str:
    """Build WebAuthn registration options for the user (excludes already-registered
    credentials) and stash the challenge in Redis. Returns the options JSON."""
    rows = (
        await session.execute(select(Passkey.credential_id).where(Passkey.user_id == user_id))
    ).all()
    options_json, challenge = webauthn.registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=user_id.bytes,
        user_name=user_name,
        exclude_ids=[r[0] for r in rows],
    )
    await webauthn.put_challenge(f"reg:{user_id}", challenge)
    return options_json


async def passkey_register_finish(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    credential: dict[str, Any],
    rp_id: str,
    origin: str,
    name: str,
) -> None:
    """Verify the attestation against the stashed challenge and store the credential."""
    challenge = await webauthn.pop_challenge(f"reg:{user_id}")
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
        Passkey(
            user_id=user_id,
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
    """Build passwordless (discoverable-credential) authentication options. Returns
    (options JSON, flow_id) — the flow_id keys the challenge for the finish step."""
    options_json, challenge = webauthn.authentication_options(rp_id=rp_id, allow_ids=[])
    flow_id = new_token()
    await webauthn.put_challenge(f"auth:{flow_id}", challenge)
    return options_json, flow_id


async def passkey_auth_finish(
    *,
    credential: dict[str, Any],
    flow_id: str,
    rp_id: str,
    origin: str,
    device_label: str = "",
    user_agent: str | None = None,
    ip: str | None = None,
    country_code: str | None = None,
) -> SessionResult:
    """Verify an assertion (passwordless login), bump the sign count, and start a rotating
    refresh session. Looks the credential up cross-user as ``custode_maint``."""
    challenge = await webauthn.pop_challenge(f"auth:{flow_id}")
    if challenge is None:
        raise ProblemException(
            slug="passkey_challenge_expired", title="Challenge abgelaufen", status=400
        )
    raw_id = credential.get("id") or credential.get("rawId")
    if not isinstance(raw_id, str):
        raise ProblemException(slug="passkey_invalid", title="Passkey ungültig", status=400)
    cred_id = webauthn.canonical_id(raw_id)
    async with maint_session() as session:
        pk = await session.scalar(select(Passkey).where(Passkey.credential_id == cred_id))
        if pk is None:
            raise ProblemException(slug="passkey_invalid", title="Passkey unbekannt", status=401)
        # Ein Passkey überlebt die Löschanfrage in der Tabelle (er fällt erst mit dem Nutzer per
        # ON DELETE CASCADE). Ohne diese Prüfung wäre er der bequemste Weg zurück in ein Konto,
        # dessen Löschung gerade läuft.
        _reject_deleted(await session.get(User, pk.user_id))
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
        now = datetime.now(UTC)
        pk.sign_count = new_count
        pk.last_used_at = now
        user_id = pk.user_id
        refresh_token = new_token()
        family_id = new_uuid7()
        expires_at = now + timedelta(seconds=get_settings().refresh_token_ttl_s)
        sess = AuthSession(
            user_id=user_id,
            family_id=family_id,
            refresh_hash=hash_token(refresh_token),
            device_label=device_label,
            user_agent=user_agent,
            ip=ip,
            expires_at=expires_at,
        )
        session.add(sess)
        await session.flush()
        await record_login_event(user_id=user_id, success=True, country_code=country_code)
        return SessionResult(
            user_id=user_id,
            session_id=sess.id,
            family_id=family_id,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )


async def list_passkeys(session: AsyncSession, *, user_id: uuid.UUID) -> list[PasskeyInfo]:
    """The user's registered passkeys (RLS-scoped self)."""
    rows = (
        await session.execute(
            select(Passkey.id, Passkey.name, Passkey.created_at, Passkey.last_used_at)
            .where(Passkey.user_id == user_id)
            .order_by(Passkey.created_at)
        )
    ).all()
    return [PasskeyInfo(id=r[0], name=r[1], created_at=r[2], last_used_at=r[3]) for r in rows]


async def delete_passkey(
    session: AsyncSession, *, user_id: uuid.UUID, passkey_id: uuid.UUID
) -> None:
    """Remove one of the user's passkeys (404 if it isn't theirs / doesn't exist)."""
    result = await session.execute(
        delete(Passkey)
        .where(Passkey.id == passkey_id, Passkey.user_id == user_id)
        .returning(Passkey.id)
    )
    if result.first() is None:
        raise ProblemException(slug="not_found", title="Passkey nicht gefunden", status=404)


def would_leave_no_admin(
    roles_by_membership: dict[uuid.UUID, str],
    *,
    membership_id: uuid.UUID,
    new_role: str,
) -> bool:
    """Pure invariant: would changing ``membership_id`` to ``new_role`` leave the
    household with zero admins? (Admin-Kontinuität, KONZEPT §5.1)."""
    admins = {mid for mid, role in roles_by_membership.items() if role == _ADMIN}
    if membership_id not in admins or new_role == _ADMIN:
        return False
    return admins == {membership_id}


async def get_digest_enabled(session: AsyncSession, *, household_id: uuid.UUID) -> bool:
    """Whether the weekly digest (P8-S6) is enabled for the active household (default on).
    RLS-scoped; 404 if the household isn't visible."""
    household = await session.get(Household, household_id)
    if household is None:
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    return bool((household.settings_json or {}).get("digest_enabled", True))


async def set_digest_enabled(
    session: AsyncSession, *, household_id: uuid.UUID, enabled: bool
) -> bool:
    """Toggle the weekly digest for the active household (admin). Reassigns ``settings_json`` so the
    JSONB change is tracked. Returns the new value; 404 if the household isn't visible."""
    household = await session.get(Household, household_id)
    if household is None:
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    household.settings_json = {**(household.settings_json or {}), "digest_enabled": enabled}
    await session.flush()
    return enabled


async def create_household_with_admin(*, creator_user_id: uuid.UUID, name: str) -> uuid.UUID:
    """Create a household + its first admin membership atomically."""
    household_id = new_uuid7()
    async with scoped_session(household_id=household_id, user_id=creator_user_id) as session:
        session.add(Household(id=household_id, name=name))
        session.add(Membership(household_id=household_id, user_id=creator_user_id, role=_ADMIN))
    return household_id


async def create_child(
    *, household_id: uuid.UUID, granted_by: uuid.UUID, display_name: str, username: str, pin: str
) -> uuid.UUID:
    """Admin creates a child account: a User (no e-mail/password — a username + Argon2id-hashed
    PIN) + a ``child`` Membership + a recorded parental consent, in one transaction. Scoped to the
    new child id so the ``users`` self-policy passes AND to the household so the membership/consent
    WITH CHECKs pass (``app.household_id``/``app.user_id`` both satisfied). Username is unique among
    the household's children (KONZEPT §5.1, child-safety: no wearables/vault, marketplace off by
    flag default)."""
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise ProblemException(slug="weak_pin", title="PIN muss 4-6 Ziffern haben", status=422)
    child_id = new_uuid7()
    pin_hash = hash_password(pin)
    async with scoped_session(household_id=household_id, user_id=child_id) as session:
        taken = await session.scalar(
            select(func.count())
            .select_from(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.role == _CHILD,
                Membership.deleted_at.is_(None),
                User.username == username,
            )
        )
        if taken:
            raise ProblemException(
                slug="username_taken", title="Benutzername bereits vergeben", status=409
            )
        session.add(
            User(id=child_id, display_name=display_name, username=username, pin_hash=pin_hash)
        )
        await session.flush()  # the child user must exist before the membership FK is checked
        session.add(Membership(household_id=household_id, user_id=child_id, role=_CHILD))
        session.add(
            Consent(
                household_id=household_id,
                subject_user_id=child_id,
                type="child_account",
                granted_by=granted_by,
            )
        )
        await session.flush()
    return child_id


async def record_consents(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    actor_id: uuid.UUID,
    grants: Collection[str] = (),
    revokes: Collection[str] = (),
) -> None:
    """Append consent decisions to the ledger (KONZEPT §11). Grants and revokes are BOTH inserts —
    the table has no UPDATE/DELETE grant, so a withdrawal can only ever be a new row.

    Cross-module seam for ``wearables`` (Art.-9-Consent per data type): no module reads or writes
    ``consents`` directly. The caller owns the transaction, so consent and the connection it
    belongs to commit atomically — otherwise a crash could leave data collected without a
    recorded legal basis."""
    for action, types in (("grant", grants), ("revoke", revokes)):
        for consent_type in types:
            session.add(
                Consent(
                    household_id=household_id,
                    subject_user_id=subject_user_id,
                    type=consent_type,
                    action=action,
                    granted_by=actor_id,
                )
            )
    await session.flush()


async def household_flags(session: AsyncSession, *, household_id: uuid.UUID) -> dict[str, bool]:
    """The household's effective feature flags (DEFAULT ← operator-global ← household admin).

    Cross-module seam so a module can enforce its own flag SERVER-side instead of trusting the
    UI to hide itself. ``weather`` skipped this because it would have needed an ``accounts``
    dependency it did not otherwise have; ``wearables`` already depends on this module, and for
    an Art.-9 feature "switched off" must mean the API refuses, not just that a card is hidden."""
    household = await session.get(Household, household_id)
    global_flags = {**get_settings().feature_flags, **await load_global_flags(session)}
    return get_household_flags(
        household.settings_json if household is not None else None, global_flags=global_flags
    )


async def effective_consents(
    session: AsyncSession, *, subject_user_id: uuid.UUID, types: Collection[str]
) -> dict[str, bool]:
    """Fold the append-only ledger into "is this type currently consented?" per requested type.

    ``DISTINCT ON (type) ... ORDER BY type, created_at DESC, id DESC`` = latest decision wins. The
    ``id`` tiebreak is not cosmetic: two rows written in the same transaction share ``created_at``
    (``now()`` is transaction-stable), and uuidv7 is monotonic — without it, a grant/revoke pair
    from one request would resolve arbitrarily.

    Types never mentioned in the ledger come back ``False``: absence of consent is not consent."""
    if not types:
        return {}
    rows = (
        await session.execute(
            select(Consent.type, Consent.action)
            .where(Consent.subject_user_id == subject_user_id, Consent.type.in_(list(types)))
            .distinct(Consent.type)
            .order_by(Consent.type, Consent.created_at.desc(), Consent.id.desc())
        )
    ).all()
    latest = {row[0]: row[1] for row in rows}
    return {t: latest.get(t) == "grant" for t in types}


async def child_login(
    *,
    household_id: uuid.UUID,
    username: str,
    pin: str,
    device_label: str = "",
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[SessionResult, uuid.UUID, Role]:
    """Authenticate a child by household + username + PIN and start a session scoped to that
    household. Rate-limited (Redis) so a 4-6 digit PIN can't be brute-forced; always runs one
    Argon2 verify (constant-time vs. username enumeration). Looks the child up cross-user as
    ``custode_maint`` (pre-tenant). Returns (session, household_id, child role)."""
    if await childpin.is_locked(household_id, username):
        raise ProblemException(
            slug="too_many_attempts", title="Zu viele Versuche — bitte später erneut", status=429
        )
    async with maint_session() as session:
        row = (
            await session.execute(
                select(User)
                .join(Membership, Membership.user_id == User.id)
                # Ein aufgelöster Haushalt lässt niemanden mehr herein (ADR-0085). Der Join hängt
                # bewusst NICHT allein an der getombsteten Mitgliedschaft: eine Sperre, die einen
                # vorherigen Schritt voraussetzt, ist dieselbe Fehlerklasse wie eine Kaskade, auf
                # die man sich ungeprüft verlässt.
                .join(Household, Household.id == Membership.household_id)
                .where(
                    Membership.household_id == household_id,
                    Membership.role == _CHILD,
                    Membership.deleted_at.is_(None),
                    Household.deleted_at.is_(None),
                    User.username == username,
                )
            )
        ).first()
        user = row[0] if row else None
        stored = user.pin_hash if user and user.pin_hash else _dummy_hash()
        pin_ok = verify_password(stored, pin)
        _reject_deleted(user)  # nach dem Verify — Timing-Gleichheit, s. _reject_deleted
        if user is None or user.pin_hash is None or not pin_ok:
            await childpin.record_failure(household_id, username)
            raise ProblemException(slug="invalid_pin", title="PIN falsch", status=401)
        await childpin.reset(household_id, username)
        refresh_token = new_token()
        family_id = new_uuid7()
        expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl_s)
        sess = AuthSession(
            user_id=user.id,
            family_id=family_id,
            refresh_hash=hash_token(refresh_token),
            device_label=device_label,
            user_agent=user_agent,
            ip=ip,
            expires_at=expires_at,
        )
        session.add(sess)
        await session.flush()
        return (
            SessionResult(
                user_id=user.id,
                session_id=sess.id,
                family_id=family_id,
                refresh_token=refresh_token,
                expires_at=expires_at,
            ),
            household_id,
            Role.child,
        )


def new_invite_code() -> str:
    return secrets.token_urlsafe(18)


async def create_invite(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    role: str = Role.member.value,
    expires_at: datetime,
    max_uses: int = 1,
) -> str:
    # Vierte Eintrittstür (ADR-0085). Sie ist über den Sitzungs-Widerruf bei der Auflösung bereits
    # gedeckt — und bekommt den Guard trotzdem, aus demselben Grund wie die drei anderen: eine
    # Sperre, die an einem vorherigen Schritt hängt, ist keine Sperre.
    household = await session.get(Household, household_id)
    if household is None or household.deleted_at is not None:
        raise ProblemException(slug="household_dissolved", title="Haushalt aufgelöst", status=410)
    code = new_invite_code()
    session.add(
        Invite(
            household_id=household_id,
            code=code,
            role=role,
            expires_at=expires_at,
            max_uses=max_uses,
        )
    )
    return code


async def _locked_roster(session: AsyncSession) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """Alle lebenden Mitgliedschaften des aktiven Haushalts, **mit Zeilensperre**.

    Die Admin-Kontinuität („es existiert immer ≥ 1 admin") ist eine Invariante über *mehrere*
    Zeilen, und drei Funktionen prüfen sie: ``change_role``, ``remove_member``, ``leave_household``.
    Alle drei lasen den Bestand mit einem gewöhnlichen SELECT unter READ COMMITTED — zwei
    gleichzeitige Vorgänge sahen einander also nicht. Zwei Admins, die im selben Moment austreten,
    ließen den Haushalt mit **null** Admins zurück; und da Einladungen und Rollenwechsel beide
    Admin-Rechte verlangen, gäbe es keinen Weg heraus (BUGLOG 2026-08-01).

    ``FOR UPDATE`` auf genau die Zeilen, die die Invariante ausmachen, serialisiert die drei
    gegeneinander. ``ORDER BY id`` macht die Sperrreihenfolge deterministisch, damit zwei
    gleichzeitige Vorgänge nicht über Kreuz warten.

    Rückgabe: ``(membership_id, user_id, role)``.
    """
    rows = (
        await session.execute(
            select(Membership.id, Membership.user_id, Membership.role)
            .where(Membership.deleted_at.is_(None))
            .order_by(Membership.id)
            .with_for_update()
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def change_role(
    session: AsyncSession, *, membership_id: uuid.UUID, new_role: str, household_id: uuid.UUID
) -> set[uuid.UUID]:
    """Change a member's role within the active household, protecting the last admin.
    Emits ``member.role_changed`` in the same transaction; ``household_id`` is the active
    scope (passed by the router) so the outbox WITH CHECK passes.

    Gibt die Session-Familien der betroffenen Person zurück; der Aufrufer entwertet deren
    **Access-Tokens** (``burn_access_tokens``) — nicht die Sitzungen.

    **Warum das nötig ist.** ``Principal`` wird aus dem opaken Access-Token gebaut und je Anfrage
    *nicht* gegen die Datenbank geprüft; das Token trägt die Rolle in sich. Ohne diesen Schritt
    behielte ein herabgestufter Admin seine Admin-Rechte bis zum Ablauf des Tokens. Seit 11-S1g
    ist das auf die Token-Lebensdauer begrenzt (die Rotation leitet die Rolle neu ab) statt
    unbefristet — 15 Minuten Admin nach dem Entzug sind aber immer noch 15 Minuten, und
    ``remove_member`` setzt nebenan den Maßstab, dass ein Entzug sofort wirkt.

    **Warum nicht ``revoke_all_sessions``.** Dort geht jemand; hier bleibt jemand. Eine
    Abmeldung wäre eine Nebenwirkung, die der Vorgang nicht rechtfertigt: die nächste Anfrage
    antwortet 401, der Client rotiert still, und die neue Rolle steht im frischen Token.
    """
    # Exclude soft-deleted memberships from the admin-continuity count (mirrors
    # list_members), so a removed admin row can never satisfy the last-admin guard.
    roles: dict[uuid.UUID, str] = {mid: role for mid, _, role in await _locked_roster(session)}
    if membership_id not in roles:
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    if would_leave_no_admin(roles, membership_id=membership_id, new_role=new_role):
        raise ProblemException(
            slug="forbidden",
            title="Letzter Admin kann nicht herabgestuft werden",
            status=403,
            detail="Übertrage zuerst die Admin-Rolle an ein anderes Mitglied.",
        )
    membership = await session.get(Membership, membership_id)
    if membership is None:  # pragma: no cover - existence checked against the roster above
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    membership.role = new_role
    await emit(
        session,
        type="member.role_changed",
        household_id=household_id,
        payload={
            "membership_id": str(membership_id),
            "user_id": str(membership.user_id),
            "role": new_role,
        },
    )
    return await live_session_families(user_id=membership.user_id)


async def remove_member(
    session: AsyncSession, *, membership_id: uuid.UUID, household_id: uuid.UUID
) -> set[uuid.UUID]:
    """Soft-delete a member from the active household (admin action), protecting the last
    admin — removal counts as a demotion for the invariant. Emits ``member.left`` in the
    same transaction as the ``deleted_at`` write.

    Gibt die Session-Familien zurück, deren Redis-Tokens der Aufrufer **nach dem Commit** zu
    verbrennen hat (``burn_access_families``) — ein Rollback darf keine vernichteten Tokens
    hinterlassen."""
    roles: dict[uuid.UUID, str] = {mid: role for mid, _, role in await _locked_roster(session)}
    if membership_id not in roles:
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    if would_leave_no_admin(roles, membership_id=membership_id, new_role=Role.member.value):
        raise ProblemException(
            slug="forbidden",
            title="Letzter Admin kann nicht entfernt werden",
            status=403,
            detail="Übertrage zuerst die Admin-Rolle an ein anderes Mitglied.",
        )
    membership = await session.get(Membership, membership_id)
    if membership is None:  # pragma: no cover - existence checked against the roster above
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    membership.deleted_at = datetime.now(UTC)
    # Der Zugang endet SOFORT, nicht erst mit dem nächsten Outbox-Tick: `Principal` wird aus dem
    # opaken Access-Token gebaut und je Anfrage NICHT gegen die Datenbank geprüft — das Token trägt
    # `household_id` und `role` in sich. Ohne diesen Widerruf behielte das entfernte Mitglied bis zu
    # 15 Minuten vollen Zugriff auf genau den Haushalt, aus dem es gerade entfernt wurde.
    # Es trifft alle Sitzungen der Person, auch die für andere Haushalte: das Access-Token ist
    # haushaltsgebunden, ein selektiver Widerruf wäre also ein zweiter, schwächerer Pfad neben
    # diesem. Die Person meldet sich neu an und sieht ihre übrigen Haushalte.
    families = await revoke_all_sessions(user_id=membership.user_id)
    await emit(
        session,
        type="member.left",
        household_id=household_id,
        payload={"membership_id": str(membership_id), "user_id": str(membership.user_id)},
    )
    return families


async def leave_household(
    session: AsyncSession, *, user_id: uuid.UUID, household_id: uuid.UUID
) -> set[uuid.UUID]:
    """Den aktiven Haushalt aus eigenem Antrieb verlassen (KONZEPT §5.1).

    **Warum das nicht `remove_member` mit der eigenen ID ist.** Jene Route verlangt `AdminPrincipal`
    — ein Mitglied könnte sie gar nicht aufrufen, und sie zu öffnen hieße, eine Admin-Route für
    einen Sonderfall aufzuweichen. Der Austritt ist kein Entfernen durch jemand anderen: er trifft
    immer die aufrufende Person, braucht also keine Berechtigung über die Mitgliedschaft hinaus,
    aber eigene Abweisungsgründe.

    **Drei Fälle, drei Antworten** — alle nur relevant, wenn die Person Admin ist:

    - Sie ist das **einzige** Mitglied → ``sole_member`` (409). Das wäre kein Austritt, sondern
      eine Auflösung: zurückbliebe ein Haushalt ohne jedes Mitglied, in den niemand mehr
      hineinkommt, weil Einladungen einen Admin brauchen. Das Auflösen ist ein eigener Slice
      (11-S1e); bis dahin ist ein ehrliches Nein besser als eine Schaltfläche, die Daten
      verwaist. **Achtung, bewusster Unterschied:** die *Kontolöschung* lässt diesen Fall zu — dort
      gibt es kein „stattdessen", die Person hat ein Recht darauf, und der Haushalt endet mit ihr.
    - **Letzter Admin neben Erwachsenen** → ``last_admin`` (409), behebbar durch Rollenübergabe.
    - **Letzter Admin neben nur Kindern/Gästen** → ``only_children`` (409). Seit 11-S1e behebbar,
      nur anders: nicht durch Rollenübergabe (ein Kind kann nicht übernehmen), sondern durch
      ``POST /v1/household/dissolve``. Der Grund bleibt ein eigener, weil der Ausweg ein anderer
      ist — sie mit ``last_admin`` zusammenzufassen hieße, jemanden zu einer Rollenübergabe
      aufzufordern, für die es niemanden gibt.

    Ab da ist es derselbe Ablauf wie beim Entfernen: Tombstone, **alle** Sitzungen widerrufen und
    ``member.left`` in derselben Transaktion. Gibt die Session-Familien zurück; der Aufrufer
    verbrennt ihre Redis-Tokens (Begründung der Reihenfolge in ``remove_member``).
    """
    rows = await _locked_roster(session)
    own = next((row for row in rows if row[1] == user_id), None)
    if own is None:  # pragma: no cover - ein Principal ohne Mitgliedschaft kommt nicht bis hier
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    membership_id, _, own_role = own

    # Ein Kind kann sich hier nicht selbst hinauswerfen — nicht aus Bevormundung, sondern weil es
    # für dieses Konto **keinen Weg zurück** gibt: es hat weder E-Mail noch Passwort, `child_login`
    # verlangt eine lebende Mitgliedschaft, und `accept_invite` setzt eine Sitzung voraus, die das
    # Kind ohne Login nicht herstellen kann. Der Austritt wäre also keine Ausübung eines Rechts,
    # sondern eine unwiderrufliche Selbst-Aussperrung samt Punktestand und Beiträgen — hinter einem
    # einzigen Bestätigungsdialog. Das Entfernen durch die Verwaltung bleibt der richtige Weg.
    if own_role == Role.child.value:
        raise ProblemException(
            slug="child_cannot_leave",
            title="Das muss die Verwaltung machen",
            status=409,
            detail="Ein Kinder-Konto käme ohne E-Mail und Passwort nicht wieder hinein. "
            "Bitte ein erwachsenes Mitglied darum, das Konto zu entfernen.",
        )

    if own_role == Role.admin.value:
        other_roles = [row[2] for row in rows if row[0] != membership_id]
        if not other_roles:
            raise ProblemException(
                slug="sole_member",
                title="Du bist das einzige Mitglied",
                status=409,
                detail="Einen Haushalt, in dem sonst niemand ist, kann man nicht verlassen — "
                "er müsste aufgelöst werden.",
            )
        reason = exit_blocker_reason(other_roles)
        if reason is not None:
            raise ProblemException(
                slug=reason,
                title=(
                    "Erst die Admin-Rolle übergeben"
                    if reason == "last_admin"
                    else "Dieser Haushalt muss aufgelöst werden"
                ),
                status=409,
                detail=(
                    "Übertrage zuerst die Admin-Rolle an ein anderes Mitglied."
                    if reason == "last_admin"
                    else "Außer dir leben hier nur Kinder oder Gäste — niemand kann die "
                    "Verwaltung übernehmen."
                ),
            )

    membership = await session.get(Membership, membership_id)
    if membership is None:  # pragma: no cover - existence checked against the roster above
        raise ProblemException(slug="not_found", title="Mitgliedschaft nicht gefunden", status=404)
    membership.deleted_at = datetime.now(UTC)
    families = await revoke_all_sessions(user_id=user_id)
    await emit(
        session,
        type="member.left",
        household_id=household_id,
        payload={"membership_id": str(membership_id), "user_id": str(user_id)},
    )
    return families


async def dissolve_household(
    session: AsyncSession, *, household_id: uuid.UUID, actor_id: uuid.UUID
) -> set[uuid.UUID]:
    """Einen Haushalt auflösen (Art. 17, KONZEPT §5.1, ADR-0085).

    **Die Operation, die zwei Sackgassen öffnet.** Der Selbst-Austritt lehnt für Alleinstehende mit
    ``sole_member`` ab, die Kontolöschung mit ``only_children`` — beide verweisen hierher, und bis
    zu diesem Slice konnte es niemand tun. Bei ``only_children`` sperrte das eine Person aus ihrem
    Art.-17-Recht aus.

    **Die Admin-Kontinuität wird ausdrücklich freigegeben, nicht umgangen.** Diese Funktion liest
    denselben mit ``FOR UPDATE`` gesperrten Bestand wie ``leave_household`` und ``change_role``,
    ruft ``would_leave_no_admin`` aber bewusst **nicht**: KONZEPT §5.1 verlangt „es existiert immer
    ≥ 1 Admin", und die Auflösung ist die einzige Operation, die das legitim beendet. Die Freigabe
    gehört in dieselbe gesperrte Transaktion wie die Prüfung, die sie ersetzt — sonst könnte ein
    gleichzeitiger Rollenwechsel dazwischenfahren.

    **Keine Blocker.** Symmetrisch welche einzubauen wäre ein Zirkel: das hier *ist* der Ausweg.

    Reihenfolge in dieser Transaktion:

    1. Bestand sperren (``_locked_roster``).
    2. Haushalt tombstonen. **Nicht** „ab sofort wirksam": die vier Eintrittstüren lesen in
       eigenen Verbindungen unter READ COMMITTED und sehen den Tombstone erst nach dem **Commit**.
       Das Fenster zwischen dem Sitzungs-Widerruf (Schritt 3, committet je Mitglied sofort) und
       dem Commit ist real — wer sich genau dort neu anmeldet, bekommt eine Sitzung auf einen
       Haushalt, der gerade verschwindet, und sie steht nicht mehr im zurückgegebenen
       ``families``-Satz. Das Fenster ist sub-sekündlich, aber es ist keins von null; die
       eigentliche Abhilfe gehört in ``refresh`` (dort wird die Mitgliedschaft je Rotation gar
       nicht geprüft) und ist als eigener Punkt notiert.
    3. Je Mitgliedschaft: Tombstone + ``member.left``. Dieselben Handler wie beim Einzelaustritt
       entwerten Feed-Token, legen CalDAV-Abos still und löschen Art.-9-Daten.
    4. ``household.dissolved`` — trägt die Ökonomie über **alle** Mitglieder in fester Reihenfolge
       (Begründung in ``app/household_dissolution.py``).
    5. Kinder-Konten vormerken: sie haben kein Login außerhalb dieses Haushalts und wären sonst
       unerreichbar **und** von keinem Löschjob erfassbar.

    Gibt die Session-Familien **aller** Mitglieder zurück; der Aufrufer verbrennt ihre
    Redis-Tokens. Ohne das behielte jedes Mitglied bis zu 15 Minuten vollen Zugriff.
    """
    household = await session.get(Household, household_id)
    if household is None:  # pragma: no cover - der Principal impliziert den Haushalt
        raise ProblemException(slug="not_found", title="Haushalt nicht gefunden", status=404)
    if household.deleted_at is not None:
        raise ProblemException(
            slug="already_dissolved", title="Haushalt ist bereits aufgelöst", status=409
        )

    roster = await _locked_roster(session)
    now = datetime.now(UTC)
    household.deleted_at = now

    families: set[uuid.UUID] = set()
    candidates: list[uuid.UUID] = []
    for membership_id, member_id, role in roster:
        row = await session.get(Membership, membership_id)
        if row is None:  # pragma: no cover - kommt aus dem gesperrten Bestand
            continue
        row.deleted_at = now
        families |= await revoke_all_sessions(user_id=member_id)
        await emit(
            session,
            type="member.left",
            household_id=household_id,
            payload={"membership_id": str(membership_id), "user_id": str(member_id)},
        )
        if role == Role.child.value:
            candidates.append(member_id)

    await emit(
        session,
        type="household.dissolved",
        household_id=household_id,
        payload={"household_id": str(household_id), "actor_id": str(actor_id)},
    )

    for candidate_id in candidates:
        if not await _account_dies_with_this_household(candidate_id, household_id=household_id):
            continue
        # In DERSELBEN Transaktion, mit transaktionslokal umgeschaltetem `app.user_id`: die
        # `user_visibility`-Policy erlaubt das UPDATE nur auf `id = app.user_id`, die Grenze zieht
        # also die Datenbank und nicht dieser Code — und weil `set_config(..., true)` nur bis zum
        # Ende der Transaktion gilt, bleibt alles-oder-nichts erhalten.
        #
        # Die erste Fassung öffnete hier eine eigene Session. Die committet sofort, während der
        # Rest noch offen ist: rollt die äußere Transaktion danach zurück (ein Redis-Ausfall im
        # anschließenden `burn_access_families` genügt), stünde ein lebender Haushalt mit
        # vorgemerkten Kinder-Konten da — unwiderruflich, unbemerkt, und die Kinder könnten es
        # selbst nicht sehen. Die Begründung „wir fehlen Richtung mehr Löschung" stammt vom
        # Sitzungs-Widerruf, wo ein Fehlschlag eine erneute Anmeldung kostet. Hier kostet er ein
        # Konto.
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(candidate_id)}
        )
        try:
            account = await session.get(User, candidate_id)
            if account is not None and account.deleted_at is None:
                account.deleted_at = now
                await session.flush()
        finally:
            await session.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(actor_id)}
            )

    return families


async def _account_dies_with_this_household(user_id: uuid.UUID, *, household_id: uuid.UUID) -> bool:
    """Ob dieses Konto **ohne** diesen Haushalt gar nicht mehr existieren kann.

    **Die Rolle allein reicht als Kriterium nicht** — das war ein echter Fund im adversarialen
    Durchgang zu diesem Slice. ``child`` ist eine *Mitgliedschafts*-Rolle, kein Kontotyp: ein Admin
    kann ein erwachsenes Mitglied per ``PATCH /v1/household/members/{id}`` auf ``child`` herabstufen
    und dann auflösen. Mit „Rolle == child" als Bedingung hätte er damit das **Konto** dieser Person
    zur endgültigen Löschung vorgemerkt — haushaltsübergreifend, ohne Zustimmung, ohne Rücknahme.
    Aus einer Verwaltungsbefugnis wäre eine Konto-Vernichtungs-Primitive geworden.

    Geprüft wird deshalb die Eigenschaft, die den Tombstone überhaupt rechtfertigt:

    1. **Kein eigener Anmeldeweg** — kein ``email``, kein ``password_hash``. Genau das legt
       ``create_child`` an; ein Konto mit E-Mail kann sich zurückholen (Passwort-Reset), ein Konto
       ohne kann es nicht.
    2. **Keine weitere lebende Mitgliedschaft.** Ein Kinder-Konto in einem zweiten Haushalt bleibt
       dort erreichbar — es mit diesem Haushalt zu beenden wäre schlicht falsch.

    Läuft als ``custode_maint``: die zweite Frage ist haushaltsübergreifend, und die Session des
    Admins sähe fremde Haushalte nicht.
    """
    async with maint_session() as probe:
        row = (
            await probe.execute(select(User.email, User.password_hash).where(User.id == user_id))
        ).first()
        if row is None:  # pragma: no cover - kommt aus dem gesperrten Bestand
            return False
        email, password_hash = row
        if email is not None or password_hash is not None:
            return False
        elsewhere = await probe.scalar(
            select(func.count())
            .select_from(Membership)
            .join(Household, Household.id == Membership.household_id)
            .where(
                Membership.user_id == user_id,
                Membership.household_id != household_id,
                Membership.deleted_at.is_(None),
                Household.deleted_at.is_(None),
            )
        )
    return not elsewhere


@dataclass(frozen=True)
class HouseholdMembership:
    """One of a user's household memberships (for the household picker / switch)."""

    household_id: uuid.UUID
    name: str
    role: str


@dataclass(frozen=True)
class DeletionBlocker:
    """Ein Haushalt, der die Kontolöschung aufhält, und warum."""

    household_id: uuid.UUID
    name: str
    reason: str


def exit_blocker_reason(other_roles: Collection[str]) -> str | None:
    """Ob ein **Admin** diesen Haushalt verlassen kann — und wenn nicht, warum (KONZEPT §5.1).

    Reine Funktion über die Rollen der *übrigen* Mitglieder (ohne die eigene). Sie ist geteilt:
    die Kontolöschung (`account_deletion_blockers`) und der Selbst-Austritt (`leave_household`)
    stellen dieselbe Frage, und zwei getrennte Fassungen liefen unweigerlich auseinander — die eine
    bekäme eine neue Rolle beigebracht, die andere nicht.

    Für Mitglieder, Kinder und Gäste gibt es nie einen Blocker; die Frage stellt sich nur, wenn die
    ausscheidende Person Admin ist. Der Aufrufer prüft das.

    - **Niemand sonst da** → ``None``. Was dann mit dem leeren Haushalt geschieht, ist eine Frage
      des Aufrufers, nicht dieser Invariante: die Kontolöschung lässt ihn zurück (offener Punkt,
      s. dort), der Selbst-Austritt lehnt gesondert ab (``sole_member``).
    - **Es gibt einen zweiten Admin** → ``None``, die Kontinuität ist gewahrt.
    - **Nur Erwachsene ohne Admin-Rolle** → ``last_admin``: behebbar, jemand kann übernehmen.
    - **Nur Kinder und Gäste** → ``only_children``: niemand *kann* übernehmen. Seit 11-S1e ist der
      Ausweg die Haushaltsauflösung, nicht die Rollenübergabe — deshalb weiterhin ein eigener
      Grund. Beide Fälle gleich zu benennen, schickte die Person zu einer Übergabe, für die es
      keinen Empfänger gibt.
    """
    if not other_roles:
        return None
    if any(role == Role.admin.value for role in other_roles):
        return None
    adults = [role for role in other_roles if role in (Role.admin.value, Role.member.value)]
    return "last_admin" if adults else "only_children"


async def account_deletion_blockers(*, user_id: uuid.UUID) -> list[DeletionBlocker]:
    """Haushalte, in denen diese Person nicht einfach verschwinden kann (KONZEPT §5.1).

    Genau ein Fall hält auf: **letzter Admin eines Haushalts, in dem noch andere sind.** Ohne sie
    gäbe es niemanden mehr, der Mitglieder verwalten, Einladungen aussprechen oder den Haushalt
    auflösen könnte — die Verbliebenen säßen in einem Haushalt fest, den niemand mehr führt.
    KONZEPT §5.1 nennt die Admin-Kontinuität ausdrücklich („es existiert immer ≥ 1 Admin").

    **Der Ein-Personen-Haushalt hält NICHT auf.** Dort ist „übertrage zuerst die Admin-Rolle"
    unerfüllbar — es gibt niemanden. Er verschwindet mit der Person; das ist der einzige
    widerspruchsfreie Ausgang. (Die Haushaltslöschung selbst ist ein eigener Slice; bis dahin
    bleibt der leere Haushalt stehen und wird hier ausdrücklich als offener Punkt geführt.)

    **Und der Fall dazwischen, der beim Bauen auffiel:** ein Haushalt mit dieser Person und nur
    noch **Kindern**. Ein Kind kann die Admin-Rolle nicht übernehmen — „übertrage zuerst" wäre
    genauso unerfüllbar wie im Ein-Personen-Haushalt, und ein pauschales „es sind ja noch andere
    da" sperrte die Person **für immer** aus ihrem eigenen Löschrecht. Es hält trotzdem auf, aber
    mit eigenem Grund (``only_children``): dieser Haushalt muss aufgelöst werden, und das kann
    heute noch niemand. Zwei verschiedene Sackgassen verdienen zwei verschiedene Antworten — eine
    davon ist behebbar, die andere wartet auf die Haushaltslöschung.

    Läuft als ``custode_maint``: eine Person kann in mehreren Haushalten Mitglied sein, die Prüfung
    ist also cross-household — genau wie der Login-Bootstrap.
    """
    blockers: list[DeletionBlocker] = []
    async with maint_session() as session:
        rows = (
            await session.execute(
                select(Household.id, Household.name)
                .join(Membership, Membership.household_id == Household.id)
                .where(
                    Membership.user_id == user_id,
                    Membership.deleted_at.is_(None),
                    Household.deleted_at.is_(None),
                    Membership.role == Role.admin.value,
                )
            )
        ).all()
        for household_id, name in rows:
            others = (
                await session.execute(
                    select(Membership.id, Membership.role).where(
                        Membership.household_id == household_id,
                        Membership.user_id != user_id,
                        Membership.deleted_at.is_(None),
                    )
                )
            ).all()
            reason = exit_blocker_reason([role for _, role in others])
            if reason is None:
                continue
            blockers.append(DeletionBlocker(household_id=household_id, name=name, reason=reason))
    return blockers


def _deletion_blocker_detail(blockers: list[DeletionBlocker]) -> str:
    """Zwei Sackgassen, zwei Sätze — eine ist behebbar, die andere nicht (noch nicht)."""
    parts: list[str] = []
    transferable = [b.name for b in blockers if b.reason == "last_admin"]
    if transferable:
        parts.append(
            "In diesen Haushalten bist du die einzige Person mit Admin-Rechten: "
            + ", ".join(transferable)
            + ". Übertrage die Rolle an ein anderes erwachsenes Mitglied."
        )
    children_only = [b.name for b in blockers if b.reason == "only_children"]
    if children_only:
        parts.append(
            "In diesen Haushalten leben außer dir nur Kinder: "
            + ", ".join(children_only)
            + ". Ein Kind kann die Verwaltung nicht übernehmen — der Haushalt muss aufgelöst "
            "werden. Bitte melde dich beim Betreiber."
        )
    return " ".join(parts)


async def request_account_deletion(*, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Das eigene Konto zur Löschung vormerken (Art. 17, KONZEPT §5.1).

    **Zweistufig, und das ist Absicht.** Sofort: das Konto ist gesperrt (``deleted_at`` gesetzt,
    alle Sitzungen widerrufen, jede der fünf Anmeldetüren weist ab). Erst nach der Karenz von
    ``retention_days`` räumt der Reaper die Daten endgültig. Die Frist schützt vor der
    Fehlbedienung und vor einem übernommenen Konto — und sie nutzt die Maschinerie, die es schon
    gibt, statt eine zweite danebenzustellen.

    **Der Austritt aus allen Haushalten geschieht SOFORT, nicht erst nach der Karenz.** Für jeden
    Haushalt wird die Mitgliedschaft getombstonet und ``member.left`` emittiert — dieselben vier
    Handler wie beim Entfernen durch einen Admin entwerten dann den ICS-Feed-Token, legen die
    CalDAV-Abos still, löschen die Art.-9-Wearable-Daten und lösen die Handelspositionen auf.

    Warum nicht erst mit dem Purge: die Karenz schützt davor, dass jemand sein **Konto** aus
    Versehen wegwirft. Sie ist kein Grund, dreißig Tage lang weiter Gesundheitsdaten einer Person
    abzuholen, die gerade Löschung verlangt hat — und der Feed-Token ist unauthentifiziert, an
    nichts gebunden und hat kein Ablaufdatum. Beim ersten Bau fehlte dieser Schritt, und damit lief
    für ein selbst gelöschtes Konto **keiner** der vier Handler; genau die Lücke, die 11-S1a für den
    Austritt geschlossen hatte, war auf dem Nachbarpfad wieder offen.

    Die Kehrseite gehört gesagt: damit ist der Antrag **nicht zurücknehmbar**. Ein Undo gibt es
    ohnehin nicht, aber es wäre nach diesem Schritt auch nicht mehr billig — die Person wäre aus
    allen Haushalten heraus.

    Gibt die Session-Familien zurück; der Aufrufer verbrennt ihre Redis-Tokens (wie beim
    Entfernen eines Mitglieds).

    409 mit der Liste der Haushalte, die aufhalten — nie eine stille Teil-Löschung.
    """
    blockers = await account_deletion_blockers(user_id=user_id)
    if blockers:
        raise ProblemException(
            slug="last_admin",
            title="Erst die Admin-Rolle übergeben",
            status=409,
            detail=_deletion_blocker_detail(blockers),
            extra={"households": [str(b.household_id) for b in blockers]},
        )

    # Erst austreten, dann sperren. Die Reihenfolge zählt: `member.left` wird in der Transaktion
    # des jeweiligen Haushalts emittiert (die Outbox-Zeile trägt `household_id` und hat ein
    # WITH CHECK darauf) — nach dem Sperren wäre die Person dafür kein Mitglied mehr.
    households = await list_user_households(user_id=user_id)
    for membership in households:
        async with scoped_session(household_id=membership.household_id, user_id=user_id) as session:
            row = await session.scalar(
                select(Membership).where(
                    Membership.user_id == user_id, Membership.deleted_at.is_(None)
                )
            )
            if row is None:  # bereits ausgetreten — idempotent
                continue
            row.deleted_at = datetime.now(UTC)
            await emit(
                session,
                type="member.left",
                household_id=membership.household_id,
                payload={"membership_id": str(row.id), "user_id": str(user_id)},
            )

    families: set[uuid.UUID] = set()
    # Unter der eigenen Session der Person, nicht unter maint: `custode_maint` darf `users` nur
    # LESEN, und das ist richtig so. Die RLS-Policy `user_visibility` erlaubt ein UPDATE nur auf
    # `id = app.user_id` (WITH CHECK) — die Datenbank stellt also sicher, dass hier niemand ein
    # fremdes Konto löscht, nicht bloß dieser Code. Der Haushalt spielt keine Rolle (eine Person
    # kann in mehreren sein), deshalb dieselbe Form wie beim Passwort-Reset.
    async with scoped_session(household_id=user_id, user_id=user_id) as session:
        user = await session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            # Schon vorgemerkt: idempotent, keine zweite Frist, kein Fehler.
            return families
        user.deleted_at = datetime.now(UTC)
        families = await revoke_all_sessions(user_id=user_id)
    return families


async def list_user_households(*, user_id: uuid.UUID) -> list[HouseholdMembership]:
    """All households the user belongs to. Cross-household read for the picker — runs
    as ``custode_maint`` (read-only), like the login bootstrap. Soft-deleted memberships
    are dead for authorization purposes (a removed member must not see the household in
    the picker while the reaper hasn't hard-deleted the row yet)."""
    async with maint_session() as session:
        rows = (
            await session.execute(
                select(Household.id, Household.name, Membership.role)
                .join(Membership, Membership.household_id == Household.id)
                .where(
                    Membership.user_id == user_id,
                    Membership.deleted_at.is_(None),
                    Household.deleted_at.is_(None),
                )
                .order_by(Household.name)
            )
        ).all()
    return [HouseholdMembership(household_id=r[0], name=r[1], role=r[2]) for r in rows]


async def get_active_role(*, user_id: uuid.UUID, household_id: uuid.UUID) -> Role | None:
    """The user's role in ``household_id`` (membership check before a switch), or
    ``None`` if not a member. Read-only cross-household lookup (``custode_maint``) — we
    must not scope to a user-supplied household to check it (that would leak members).
    A soft-deleted membership is no membership: without this filter a removed member
    could re-enter via switch until the 30-day reaper hard-deletes the row.

    Dasselbe gilt für den **Haushalt**: ein aufgelöster Haushalt (ADR-0085) ist keiner mehr. Die
    Mitgliedschaften werden bei der Auflösung zwar alle getombstonet, aber diese Bedingung hier
    hängt dann an einem vorherigen Schritt — und genau diese Fehlerklasse hat diese Phase
    mehrfach eingesammelt. Der Join kostet nichts und macht die Sperre eigenständig."""
    async with maint_session() as session:
        role = await session.scalar(
            select(Membership.role)
            .join(Household, Household.id == Membership.household_id)
            .where(
                Membership.user_id == user_id,
                Membership.household_id == household_id,
                Membership.deleted_at.is_(None),
                Household.deleted_at.is_(None),
            )
        )
    return Role(role) if role is not None else None


async def resolve_refresh_scope(
    *, user_id: uuid.UUID, cached: tuple[uuid.UUID, Role] | None
) -> tuple[uuid.UUID, Role] | None:
    """Den Haushalts-Scope einer Sitzung **je Rotation** aus der Datenbank ableiten.

    ``refresh`` mintete das neue Access-Token bis 11-S1g mit genau dem, was in Redis unter
    ``active_household:<family>`` stand — 30 Tage lang (die Lebensdauer des Refresh-Tokens) und
    ohne jede Rückfrage. Das ist die teuerste Fehlerklasse dieser Codebasis: **die Prüfung hing an
    einer Repräsentation statt am Begriff.** Der Redis-Eintrag sagt nur, welchen Haushalt die
    Person zuletzt *gewählt* hat — gesetzt hat ihn sie selbst, per Haushaltswechsel. Wer die
    Repräsentation setzen kann, ist dieselbe Person, die von der Entscheidung profitiert; sie ist
    damit kein Kriterium, sondern ein Hebel.

    Was das offenließ, obwohl 11-S1a bis 11-S1e genau das schließen sollten:

    * Ein **aufgelöster** Haushalt (ADR-0085) und eine **entfernte** Mitgliedschaft beenden den
      Zugang über den Sitzungs-Widerruf. Wer sich im Sekundenfenster davor neu anmeldet, hält eine
      Sitzung, die in keinem widerrufenen ``families``-Satz steht — und rotiert sie weiter.
    * Ein per ``change_role`` **herabgestufter Admin** behielt seine Admin-Rolle unbefristet:
      ``change_role`` widerruft, anders als ``remove_member``, keine Sitzungen, und der Refresh
      schrieb die alte Rolle aus Redis fort.

    Der zwischengespeicherte Wert ist deshalb nur noch ein **Hinweis auf den Haushalt**; ob es ihn
    noch gibt, ob die Mitgliedschaft lebt und welche Rolle heute gilt, beantwortet
    ``get_active_role`` gegen die Datenbank — dieselbe Prüfung, die der Haushaltswechsel seit jeher
    macht. ``None`` heißt: dieses Token bekommt **keinen** Scope.

    Bewusst **kein** Auto-Scope auf eine einzige Mitgliedschaft (``resolve_sole_household``): das
    gehört zur Anmeldung. Eine Rotation darf einen Scope bestätigen, aber keinen neuen vergeben.
    """
    if cached is None:
        return None
    household_id, _ = cached
    role = await get_active_role(user_id=user_id, household_id=household_id)
    if role is None:
        return None
    # Die Rolle kommt aus der Datenbank, nicht aus dem Merkzettel — eine Herabstufung wirkt damit
    # mit der nächsten Rotation, auch wenn niemand die Sitzung angefasst hat.
    return household_id, role


async def resolve_sole_household(*, user_id: uuid.UUID) -> tuple[uuid.UUID, Role] | None:
    """The user's only (live) household membership, or ``None`` when they have zero or
    several. Fresh logins auto-scope to it: most accounts belong to exactly one
    household, and landing there beats a context-less session where every module
    screen 403s (P8 Mobile-/Prod-QA finding). Multi-household users keep the explicit
    picker — the choice stays theirs."""
    memberships = await list_user_households(user_id=user_id)
    if len(memberships) != 1:
        return None
    only = memberships[0]
    return only.household_id, Role(only.role)


async def accept_invite(*, user_id: uuid.UUID, code: str) -> tuple[uuid.UUID, Role]:
    """Join a household via invite code. The code is looked up cross-household (maint,
    read-only); the membership insert + use-count bump then run as ``custode_app``
    scoped to the *invite's* household (server-derived, not user input). Raises on an
    unknown (404) / expired (410) / exhausted (409) code, or an existing membership (409)."""
    async with maint_session() as session:
        invite = await session.scalar(select(Invite).where(Invite.code == code))
        if invite is None:
            raise ProblemException(slug="not_found", title="Einladung nicht gefunden", status=404)
        if invite.expires_at <= datetime.now(UTC):
            raise ProblemException(slug="invite_expired", title="Einladung abgelaufen", status=410)
        invite_id = invite.id
        household_id = invite.household_id
        role = invite.role
        # Ein aufgelöster Haushalt nimmt niemanden mehr auf (ADR-0085). Ohne diese Prüfung wäre
        # eine noch gültige Einladung der Weg zurück in einen Haushalt, den es nicht mehr gibt —
        # samt frischer Mitgliedschaft, die kein Löschjob erwartet.
        dissolved = await session.scalar(
            select(Household.deleted_at).where(Household.id == household_id)
        )
        if dissolved is not None:
            raise ProblemException(
                slug="household_dissolved", title="Haushalt aufgelöst", status=410
            )
        already = await session.scalar(
            select(Membership.id).where(
                Membership.household_id == household_id, Membership.user_id == user_id
            )
        )
        if already is not None:
            raise ProblemException(slug="already_member", title="Bereits Mitglied", status=409)

    # Writes as custode_app, scoped to the invite's household (bootstrap path). The
    # use-bump and the insert share one transaction — a failed insert rolls back the use.
    async with scoped_session(household_id=household_id, user_id=user_id) as session:
        claimed = await session.scalar(
            update(Invite)
            .where(Invite.id == invite_id, Invite.uses < Invite.max_uses)
            .values(uses=Invite.uses + 1)
            .returning(Invite.id)
        )
        if claimed is None:
            raise ProblemException(
                slug="invite_exhausted", title="Einladung aufgebraucht", status=409
            )
        session.add(Membership(household_id=household_id, user_id=user_id, role=role))
        try:
            await session.flush()
        except IntegrityError as exc:  # raced another accept of the same invite
            raise ProblemException(
                slug="already_member", title="Bereits Mitglied", status=409
            ) from exc
        # Transactional outbox: the join event lands in the SAME tx as the membership +
        # use-bump, so it can never be lost or leak from a rolled-back accept.
        await emit(
            session,
            type="member.joined",
            household_id=household_id,
            payload={"user_id": str(user_id), "role": role},
        )
    return household_id, Role(role)


@dataclass(frozen=True)
class Member:
    """A member of the active household (with display name for the roster)."""

    membership_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    display_name: str


async def list_members(session: AsyncSession) -> list[Member]:
    """Members of the *active* household. The session must already be RLS-scoped, so
    this only ever returns the active household's roster."""
    rows = (
        await session.execute(
            select(Membership.id, Membership.user_id, Membership.role, User.display_name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.deleted_at.is_(None))
            .order_by(User.display_name)
        )
    ).all()
    return [Member(membership_id=r[0], user_id=r[1], role=r[2], display_name=r[3]) for r in rows]


@dataclass(frozen=True)
class DigestTarget:
    """A household plus the adult members who should receive its weekly digest (P8-S6). Built under
    the **maint role** (cross-household). The caller honours the per-household ``settings_json``
    opt-out (``digest_enabled``) and skips households with no recipients."""

    household_id: uuid.UUID
    name: str
    settings_json: dict[str, Any]
    recipient_emails: tuple[str, ...]


async def list_digest_recipients(session: AsyncSession) -> list[DigestTarget]:
    """Every household with its adult (admin/member) members' e-mail addresses, for the weekly
    digest fan-out (ARCHITECTURE §9). Runs under the **maint role**, which sees all households, so
    the join is explicit (no RLS scope). Children/guests and members without an e-mail are excluded;
    households with no eligible recipient are dropped."""
    rows = (
        await session.execute(
            select(Household.id, Household.name, Household.settings_json, User.email)
            .join(Membership, Membership.household_id == Household.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.deleted_at.is_(None),
                Membership.role.in_(("admin", "member")),
                User.email.is_not(None),
            )
            .order_by(Household.id)
        )
    ).all()
    grouped: dict[uuid.UUID, tuple[str, dict[str, Any], list[str]]] = {}
    for household_id, name, settings_json, email in rows:
        _name, _settings, emails = grouped.setdefault(household_id, (name, settings_json or {}, []))
        emails.append(email)
    return [
        DigestTarget(
            household_id=hid, name=name, settings_json=settings, recipient_emails=tuple(emails)
        )
        for hid, (name, settings, emails) in grouped.items()
    ]
