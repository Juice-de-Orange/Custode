"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.null import NullLlm
from app.adapters.ollama.llm import OllamaLlm
from app.caldav_factory import build_caldav
from app.export_policy import ATTACHMENT_COLUMNS, EXCLUDED
from app.export_policy import POLICY as EXPORT_POLICY
from app.kernel.http.export import router as export_router
from app.kernel.http.health import router as health_router
from app.kernel.http.problem import install_problem_handlers
from app.kernel.http.stream import router as stream_router
from app.kernel.ports.caldav import CaldavPort
from app.kernel.ports.llm import LlmPort
from app.kernel.ports.mail import MailPort
from app.kernel.redis import close_redis
from app.kernel.tenancy.middleware import RequestContextMiddleware
from app.logging import configure_logging, get_logger
from app.mail_factory import build_mail
from app.modules.accounts.router import account_router, auth_router, household_router
from app.modules.backoffice.router import banners_router, ops_router
from app.modules.calendar.router import calendar_router
from app.modules.capture.router import capture_router
from app.modules.comments.router import comments_router
from app.modules.economy.router import economy_router
from app.modules.feedback.router import feedback_router
from app.modules.guides.router import guides_router
from app.modules.links.router import links_router
from app.modules.marketplace.router import marketplace_router
from app.modules.mealplanner.router import mealplan_router
from app.modules.messaging.router import letters_router
from app.modules.notes.router import notes_router
from app.modules.nutrition.router import ingredients_router
from app.modules.recipes.router import recipes_router
from app.modules.scheduling.router import scheduling_router
from app.modules.shopping.router import shopping_router
from app.modules.tasks.router import tasks_router
from app.modules.vault.router import vault_router
from app.modules.wearables.router import wearables_router
from app.modules.weather.router import weather_router
from app.settings import Settings, get_settings, require_runtime_settings
from app.telemetry import configure_telemetry, instrument_app
from app.wearable_factory import build_wearable_oauth


def _build_mail(settings: Settings) -> MailPort:
    """Choose the mail adapter at startup (ADR-0027) — see ``app.mail_factory.build_mail``."""
    return build_mail(settings)


def _build_llm(settings: Settings) -> LlmPort:
    """Choose the LLM adapter at startup (ADR-0068): a local Ollama when explicitly enabled, else
    the Null adapter (LLM disabled — the deterministic Zuruf-Parser carries the base path)."""
    if settings.ollama_enabled:
        return OllamaLlm(settings)
    return NullLlm()


def _build_request_caldav(settings: Settings) -> CaldavPort:
    """CalDAV port for the request path (write-back, P9-S4, ADR-0080) — same composition as the
    worker cron (``app.caldav_factory``); the kill switch selects the Null adapter, whose ops
    raise -> mirror writes answer 503 instead of silently diverging from the remote."""
    return build_caldav(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log = get_logger("app")
    log.info("startup", env=app.state.settings.env)
    yield
    await close_redis()
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    require_runtime_settings(settings)  # refuse to boot a misconfigured prod (BUGLOG 2026-06-17)
    configure_logging(settings)
    configure_telemetry(settings)

    app = FastAPI(
        title=f"{settings.brand_name} API",
        version="0.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mail = _build_mail(settings)
    app.state.llm = _build_llm(settings)
    app.state.caldav = _build_request_caldav(settings)
    # P9-S5: kill switch + missing credentials both select the Null adapter, whose
    # methods raise -> connecting answers 503 while reading/deleting keeps working.
    app.state.wearable_oauth = build_wearable_oauth(settings)
    # Subject-rights export (Art. 15/20): the kernel route must not name module tables, so the
    # classification travels through app.state like the ports do (E2, ADR-0039).
    app.state.export_policy = EXPORT_POLICY
    app.state.export_excluded = EXCLUDED
    app.state.export_attachment_columns = ATTACHMENT_COLUMNS

    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app)
    app.include_router(health_router)
    app.include_router(stream_router)
    app.include_router(export_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(household_router)
    app.include_router(recipes_router)
    app.include_router(ingredients_router)
    app.include_router(shopping_router)
    app.include_router(tasks_router)
    app.include_router(economy_router)
    app.include_router(marketplace_router)
    app.include_router(capture_router)
    app.include_router(calendar_router)
    app.include_router(weather_router)
    app.include_router(scheduling_router)
    app.include_router(mealplan_router)
    app.include_router(notes_router)
    app.include_router(letters_router)
    app.include_router(guides_router)
    app.include_router(comments_router)
    app.include_router(links_router)
    app.include_router(vault_router)
    app.include_router(wearables_router)
    app.include_router(feedback_router)
    app.include_router(ops_router)
    app.include_router(banners_router)
    instrument_app(app)
    return app


app = create_app()
