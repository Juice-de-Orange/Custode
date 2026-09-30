"""OpenTelemetry init (ADR-014). OTLP export only when an endpoint is set;
otherwise a local no-op provider so the app runs without a collector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.logging import get_logger
from app.settings import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_configured = False


def configure_telemetry(settings: Settings) -> None:
    global _configured
    if _configured:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )

    trace.set_tracer_provider(provider)
    _configured = True


def instrument_app(app: FastAPI) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Exclude health/metrics: high-frequency probe noise, and they trigger an
        # otel-instrumentation-fastapi bug on HEAD requests (_get_route_details →
        # AttributeError on _IncludedRouter) that turned HEAD /healthz into a 500
        # (BUGLOG 2026-06-15). Probes legitimately HEAD these endpoints.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")
    except Exception as exc:
        get_logger("telemetry").warning("otel_instrumentation_failed", error=type(exc).__name__)
