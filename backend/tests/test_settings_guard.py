"""The production guard refuses to boot when the maintenance DB URL is missing.

Regression for BUGLOG 2026-06-17: a missing CUSTODE_DATABASE_URL_MAINT silently fell
back to the app role, RLS hid every row, and login returned invalid_credentials. The
guard turns that silent misconfiguration into a hard startup failure.

``model_copy`` forces ``database_url_maint`` regardless of the ambient environment so
the test is deterministic even in CI (where the var is set for the Testcontainers DB).
"""

from __future__ import annotations

import pytest

from app.main import create_app
from app.settings import Settings, require_runtime_settings


def _prod_without_maint() -> Settings:
    return Settings(env="prod").model_copy(update={"database_url_maint": None})


def test_dev_without_maint_is_allowed() -> None:
    # Dev deliberately falls back to the app role; no maint URL required.
    settings = Settings(env="dev").model_copy(update={"database_url_maint": None})
    require_runtime_settings(settings)  # does not raise


def test_non_dev_without_maint_raises() -> None:
    with pytest.raises(RuntimeError, match="CUSTODE_DATABASE_URL_MAINT"):
        require_runtime_settings(_prod_without_maint())


def test_non_dev_with_maint_is_allowed() -> None:
    settings = Settings(env="production").model_copy(
        update={"database_url_maint": "postgresql+asyncpg://custode_maint@host/custode"}
    )
    require_runtime_settings(settings)  # does not raise


def test_create_app_refuses_misconfigured_prod() -> None:
    # The guard runs before any infra is touched, so this raises without a DB/Redis.
    with pytest.raises(RuntimeError, match="CUSTODE_DATABASE_URL_MAINT"):
        create_app(_prod_without_maint())
