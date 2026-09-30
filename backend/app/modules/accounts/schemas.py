"""HTTP request/response contracts for ``accounts`` (single source for the OpenAPI
schema → web zod client). Separate from the ORM models. E-mail is normalised here;
the service's password policy + the DB unique constraint stay authoritative, so the
schema only does cheap shape checks (and lets weak/breached passwords through to the
service, which answers with the specific 422)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.kernel.auth.context import Role


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str = Field(min_length=1, max_length=100)
    locale: str = Field(default="de", max_length=10)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("Ungültige E-Mail-Adresse.")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = Field(default=None, max_length=8)
    recovery_code: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class SessionResponse(BaseModel):
    """Lightweight session view returned by register/login/refresh and household
    switches. The cookies carry the real payload; this just tells the client who it
    is and which household is active (``None`` right after registration)."""

    user_id: uuid.UUID
    household_id: uuid.UUID | None = None
    role: Role | None = None


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str
    household_id: uuid.UUID | None
    role: Role | None
    totp_enabled: bool
    recovery_codes_remaining: int
    email_verified: bool
    flags: dict[str, bool]


class PasswordForgotRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class ProfileResponse(BaseModel):
    """Self-service profile; ``version`` is the ETag (If-Match optimistic concurrency)."""

    display_name: str
    locale: str
    work_hours: str
    dietary: list[str]
    notifications: dict[str, bool]
    version: int


class ProfileUpdate(BaseModel):
    """Partial profile update — only the provided fields change. ``display_name``/``locale`` are
    columns; the rest live in ``users.settings_json``."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    locale: str | None = Field(default=None, max_length=10)
    work_hours: str | None = Field(default=None, max_length=200)
    dietary: list[str] | None = None
    notifications: dict[str, bool] | None = None


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class PasskeyOptions(BaseModel):
    """WebAuthn ceremony options (passed verbatim to the browser ``navigator.credentials``)."""

    options: dict[str, Any]


class PasskeyRegisterComplete(BaseModel):
    credential: dict[str, Any]
    name: str = Field(default="", max_length=120)


class PasskeyLoginComplete(BaseModel):
    credential: dict[str, Any]


class PasskeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class SessionView(BaseModel):
    """One active login/device (a refresh rotation family). ``current`` marks the session
    behind the present access token, so the UI can label it and warn before self-logout."""

    family_id: uuid.UUID
    device_label: str
    user_agent: str | None
    last_used_at: datetime
    current: bool


class LoginEventResponse(BaseModel):
    """A past login attempt (security activity view). PII-free: country code only."""

    success: bool
    country_code: str | None
    created_at: datetime


class CreateHouseholdRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class JoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=48)


class CreateInviteRequest(BaseModel):
    role: Role = Role.member
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_hours: int = Field(default=168, ge=1, le=8760)


class CreateChildRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    pin: str = Field(min_length=4, max_length=8)


class ChildLoginRequest(BaseModel):
    household_id: uuid.UUID
    username: str = Field(min_length=1, max_length=50)
    pin: str = Field(min_length=1, max_length=8)


class ChildResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str


class ChangeRoleRequest(BaseModel):
    role: Role


class HouseholdSummary(BaseModel):
    household_id: uuid.UUID
    name: str
    role: Role


class InviteResponse(BaseModel):
    code: str


class DigestSetting(BaseModel):
    """Whether the weekly digest is enabled for the household (P8-S6/S7b)."""

    enabled: bool


class MemberResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    display_name: str


class DeletionBlockerResponse(BaseModel):
    """Ein Haushalt, der die Kontolöschung aufhält. ``reason`` ist ein stabiler Slug, den die
    Oberfläche in einen Satz übersetzt — nie ein fertiger Text vom Server."""

    household_id: uuid.UUID
    name: str
    reason: str


class DissolveHouseholdRequest(BaseModel):
    """Der Haushaltsname, abgetippt.

    Kein `window.confirm`: das ist die schärfste irreversible Aktion der Anwendung. Ein Wert, den
    ein Angreifer nicht kennt, macht sie gegen Clickjacking-Restrisiken unbrauchbar — und zwingt
    die Person, einen Moment innezuhalten (ADR-0085).
    """

    confirm_name: str = Field(min_length=1, max_length=200)


class DissolvePreview(BaseModel):
    """Was die Auflösung kosten wird — vor dem Knopf, nicht als Fehler danach."""

    household_name: str
    member_count: int
    child_account_count: int
