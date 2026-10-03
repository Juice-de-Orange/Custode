"""Application settings (12-factor, pydantic-settings).

All values have dev-friendly defaults so the app boots without external infra.
Override via environment variables prefixed ``CUSTODE_`` or a local ``.env``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CUSTODE_",
        extra="ignore",
    )

    # Runtime
    env: str = "dev"
    debug: bool = False
    brand_name: str = "Custode"  # display name — never hardcode elsewhere

    # Logging
    log_level: str = "INFO"
    log_json: bool = True

    # Datastores (optional in Phase 0 — app boots even if unreachable)
    database_url: str = "postgresql+asyncpg://custode_app:custode@localhost:5432/custode"
    # Superuser/owner URL used for migrations (alembic); falls back to database_url.
    database_url_admin: str | None = None
    # Maintenance role (cross-household) for the outbox dispatcher + retention jobs;
    # falls back to database_url.
    database_url_maint: str | None = None
    # Betreiber-Konsole role (ops_readonly): reads aggregate views + the operators auth table only,
    # never a fact table (ADR-0015/0071). Falls back to database_url in dev.
    database_url_ops: str | None = None
    # Betreiber-Aktionen role (ops_actions): writes the audit_log + ops-owned tables (banners,
    # operators) and runs defined action procedures (ADR-0015). Falls back to database_url in dev.
    database_url_ops_actions: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    # Local filesystem blob storage (recipe photos); None -> uploads disabled (Null-Adapter).
    storage_dir: str | None = None

    # Server-side credential encryption (ADR-0077): Fernet key for third-party secrets
    # the server must be able to USE (CalDAV passwords, wearable OAuth tokens) — unlike
    # the client-side vault. None -> dependent integrations stay off (Null/503), never a
    # crash. Generate via app.kernel.crypto.generate_key(); lives only in the .env.
    crypto_key: str | None = None  # CUSTODE_CRYPTO_KEY

    # Mail (mailpit in dev; the operator's SMTP provider in prod — ADR-0027). Secrets via env,
    # never in repo.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@localhost"  # envelope From address; display name = brand_name
    smtp_starttls: bool = False  # True for :587 STARTTLS (:465 uses implicit TLS automatically)

    # Public web origin for links in transactional e-mails (password reset, verification).
    public_base_url: str = "http://localhost:5173"

    # Observability
    service_name: str = "custode-api"
    otlp_endpoint: str | None = None
    # Build info surfaced in the ops console (§12): injected at deploy from the image tag/commit.
    git_sha: str = "unknown"
    app_version: str = "0.0.0"

    # Sessions (KONZEPT §8.5): short-lived access, long-lived rotating refresh.
    access_token_ttl_s: int = 900  # 15 min
    refresh_token_ttl_s: int = 60 * 60 * 24 * 30  # 30 days
    # Betreiber-Konsole operator session (ADR-0015): opaque bearer token in Redis.
    ops_session_ttl_s: int = 60 * 60 * 8  # 8 h

    # Outbox dispatcher + reaper (worker/scheduler; ARCHITECTURE §8.2/§8.4). The worker
    # drains due events every ``outbox_poll_interval_s``; the hourly scheduler reaper drops
    # processed rows + stale idempotency-ledger entries older than ``outbox_retention_days``.
    outbox_poll_interval_s: float = 1.0
    outbox_retention_days: int = 30
    # Sync-Batch idempotency markers (sync_client_ops); the reaper drops rows older than this.
    sync_ops_retention_days: int = 30
    # Soft-delete tombstones (deleted_at): the daily retention reaper hard-deletes rows whose
    # deleted_at is older than this — the 30-day trash window (ARCHITECTURE §9).
    retention_days: int = 30

    # Login audit (ADR-0025): the edge (Cloudflare) sets a 2-letter country header; absent ->
    # no country recorded (no own GeoIP DB). The IP itself is never stored.
    geo_country_header: str = "CF-IPCountry"

    # Global (operator-level) feature flags; household-level flags live in DB.
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    # Weather (KONZEPT §5.14, graceful enhancement). ``open-meteo`` calls the public Open-Meteo API
    # (fixed host, no key); ``null`` is the base path (no provider -> the app degrades to empty
    # forecasts). Responses are cached in Redis for ``weather_cache_ttl_s``.
    weather_provider: str = "open-meteo"
    weather_cache_ttl_s: int = 3600

    # Zuruf-LLM (Ollama). Optional enrichment of the deterministic Zuruf-Parser (graceful
    # enhancement): off by default -> the Null adapter, app works fully without an LLM. When on,
    # a *local* Ollama enriches free-text fields only; structural routing stays deterministic
    # (ADR-0068). The URL is server-config (no user input -> no SSRF). Output is schema-validated.
    ollama_enabled: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_s: float = 8.0

    # Feedback -> Issue-Tracker forwarding (graceful enhancement, ADR-0076). OFF by default -> the
    # Null adapter (no forwarding; in-app feedback + the operator inbox work regardless). When both
    # a token and a repo are set, a submission is best-effort forwarded to GitHub Issues. Fixed host
    # (no user input -> no SSRF); a forwarding failure never breaks submission. Secrets via env,
    # never in repo (like the SMTP secrets above).
    github_token: str | None = None  # CUSTODE_GITHUB_TOKEN — fine-grained PAT, Issues: read/write
    github_repo: str | None = None  # CUSTODE_GITHUB_REPO — "owner/repo"
    github_api_url: str = "https://api.github.com"
    github_timeout_s: float = 10.0

    # CalDAV pull-sync (P9-S3, ADR-0079). The kill switch turns the 15-min cron into a no-op
    # (operator-level; ARCHITECTURE: every external adapter globally off-switchable).
    # ``caldav_allow_private_urls`` relaxes ONLY the public-address SSRF check — for dev/tests
    # (Radicale in compose) and self-hosted targets (NAS Nextcloud); scheme validation,
    # credential-redirect origin-locking and size/time caps still apply. Default off.
    caldav_sync_enabled: bool = True  # CUSTODE_CALDAV_SYNC_ENABLED
    caldav_allow_private_urls: bool = False  # CUSTODE_CALDAV_ALLOW_PRIVATE_URLS
    caldav_timeout_s: float = 10.0

    # Oura wearable cloud (P9-S5, ADR-0081). Confidential OAuth2 client: the OPERATOR registers
    # the app once, so id/secret are deployment settings, never per-user. Personal Access Tokens
    # were switched off by Oura in Dec 2025 — OAuth2 is the only way in. Without credentials (or
    # with the kill switch off) the factory returns the Null adapter and connecting answers 503;
    # reading and DELETING existing connections keeps working (Graceful Enhancement). Secrets via
    # env, never in repo (like the SMTP/GitHub secrets above).
    oura_enabled: bool = True  # CUSTODE_OURA_ENABLED — kill switch per external adapter
    oura_client_id: str | None = None  # CUSTODE_OURA_CLIENT_ID
    oura_client_secret: str | None = None  # CUSTODE_OURA_CLIENT_SECRET
    oura_timeout_s: float = 10.0
    # Raw daily values are deleted after this many days (KONZEPT §11: Default 90). Its own job,
    # not the tombstone reaper — these tables forbid tombstones, so the axis is the age of the
    # measured DAY. Retention runs even with the adapter switched off: data must age out
    # regardless of whether new data arrives.
    wearable_raw_retention_days: int = 90  # CUSTODE_WEARABLE_RAW_RETENTION_DAYS


def require_runtime_settings(settings: Settings) -> None:
    """Fail loud on a misconfigured non-dev deployment.

    ``database_url_maint`` is optional in the model (dev falls back to the app role),
    but in a real deployment its absence makes ``get_maint_sessionmaker()`` silently
    fall back to ``custode_app``. The cross-household bootstrap reads (login/refresh,
    passkey/recovery lookup, the outbox dispatcher) then run without an RLS scope and
    see 0 rows — login fails with ``invalid_credentials`` (BUGLOG 2026-06-17). A silent
    fallback that breaks auth in production is worse than refusing to boot, so any
    non-``dev`` env without the maintenance URL is a hard error. Mirrors the dev/prod
    split used for cookie security (``env != "dev"``)."""
    if settings.env != "dev" and not settings.database_url_maint:
        raise RuntimeError(
            "CUSTODE_DATABASE_URL_MAINT is required when CUSTODE_ENV != 'dev'. "
            "Without it, cross-household reads fall back to the app role and RLS hides "
            "every row (login returns invalid_credentials). Point it at the custode_maint "
            "connection string."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
