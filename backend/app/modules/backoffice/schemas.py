"""HTTP contracts for the Betreiber-Konsole (`/ops`). Single source: OpenAPI -> web zod client."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

BannerLevel = Literal["info", "warning"]


class OperatorLogin(BaseModel):
    """Operator login: e-mail + password + mandatory TOTP code (ADR-0015)."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)
    totp_code: str = Field(min_length=6, max_length=10)


class OperatorSession(BaseModel):
    """Opaque operator-session bearer token (send as ``Authorization: Bearer <token>``)."""

    token: str


class OperatorMe(BaseModel):
    """The authenticated operator."""

    id: uuid.UUID
    email: str


class OperatorSummary(BaseModel):
    """One operator for the management list. NEVER exposes password_hash/totp_secret."""

    id: uuid.UUID
    email: str
    totp_enabled: bool
    is_active: bool
    created_at: datetime


class OpsPasskeyOptions(BaseModel):
    """WebAuthn ceremony options (passed verbatim to ``navigator.credentials``)."""

    options: dict[str, Any]


class OpsPasskeyLoginOptions(BaseModel):
    """Passwordless-login options + the cookieless flow handle to echo back on complete."""

    options: dict[str, Any]
    flow_id: str


class OpsPasskeyRegisterComplete(BaseModel):
    credential: dict[str, Any]
    name: str = Field(default="", max_length=120)


class OpsPasskeyLoginComplete(BaseModel):
    credential: dict[str, Any]
    flow_id: str


class OperatorPasskeySummary(BaseModel):
    """A registered operator passkey for the management list (no secret material)."""

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class OpsHealth(BaseModel):
    """Build/health info for the ops console (§12). Operator-only."""

    env: str
    app_version: str
    git_sha: str


class UsageCounters(BaseModel):
    """Global counters (aggregate view ``usage_counters``) — no per-household detail."""

    households: int
    users: int
    adult_members: int
    children: int


class DailyMetric(BaseModel):
    """One day's signup counts (aggregate view ``daily_metrics``)."""

    day: date
    new_households: int
    new_users: int


class OpsKpis(BaseModel):
    """The ops dashboard payload: global counters + the signup curve (newest day first)."""

    usage: UsageCounters
    daily: list[DailyMetric]


class BannerCreate(BaseModel):
    """Create a global banner (operator action)."""

    message: str = Field(min_length=1, max_length=500)
    level: BannerLevel = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class BannerResponse(BaseModel):
    """A global banner (ops list / app display)."""

    id: uuid.UUID
    message: str
    level: BannerLevel
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime


class OpsFlags(BaseModel):
    """Operator-set global flag overrides + the set of flaggable keys (so the console can render
    every togglable flag, including those without an override yet)."""

    overrides: dict[str, bool]
    available: list[str]


class FlagSet(BaseModel):
    """Set (or change) a global flag override."""

    enabled: bool


class HouseholdMetadata(BaseModel):
    """Org-level household metadata for support search (aggregate view ``household_metadata``):
    name, age, member counts. **No** household content (recipes/tasks/messages), per ADR-0015."""

    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    admin_count: int


class OpsFeedbackEntry(BaseModel):
    """A feedback submission as seen in the operator inbox (view ``ops_feedback``). Feedback is a
    channel addressed to support, so the message is visible here. ``diagnostics`` is the opt-in
    technical breadcrumb attachment the user chose to include (app version + recent error refs;
    no content), or null."""

    id: uuid.UUID
    household_id: uuid.UUID
    category: str
    message: str
    error_ref: str | None
    route: str | None
    diagnostics: dict[str, Any] | None = None
    created_at: datetime


class AuditLogEntry(BaseModel):
    """One append-only ``audit_log`` record for the operator audit view (ADR-0073). The log is
    **PII-free by construction** — ``detail`` carries only structured, content-free context (query
    lengths, counts, keys). Read-only; the console never mutates the trail."""

    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    household_id: uuid.UUID | None
    detail: dict[str, Any]
    request_id: str | None
