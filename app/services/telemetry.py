from typing import Optional
import importlib

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config.settings import get_settings
from app.utils.logger import logger

AzureMonitorTraceExporter = None
try:
    azure_monitor = importlib.import_module("azure.monitor.opentelemetry.exporter")
    AzureMonitorTraceExporter = getattr(azure_monitor, "AzureMonitorTraceExporter", None)
except ImportError:
    pass

telemetry_status = {
    "enabled": False,
    "connection_string": None,
    "exporter_installed": AzureMonitorTraceExporter is not None,
    "initialized": False,
    "error": None,
}

# Lightweight in-process telemetry counters for fast-path and keyword cache
telemetry_counters = {
    "fast_path_hits": 0,
    "fast_path_misses": 0,
    "keyword_cache_hits": 0,
    "keyword_cache_misses": 0,
}

telemetry_timings = {
    # name -> list of ms timings
}


def record_fast_path_hit() -> None:
    telemetry_counters["fast_path_hits"] += 1


def record_fast_path_miss() -> None:
    telemetry_counters["fast_path_misses"] += 1


def record_keyword_cache_hit() -> None:
    telemetry_counters["keyword_cache_hits"] += 1


def record_keyword_cache_miss() -> None:
    telemetry_counters["keyword_cache_misses"] += 1


def record_timing(name: str, ms: float) -> None:
    telemetry_timings.setdefault(name, []).append(ms)


def get_telemetry_snapshot() -> dict:
    return {"counters": telemetry_counters.copy(), "timings": {k: list(v) for k, v in telemetry_timings.items()}}


def get_telemetry_status() -> dict:
    return telemetry_status.copy()


def init_telemetry(app) -> None:
    settings = get_settings()
    connection_string = settings.APPLICATIONINSIGHTS_CONNECTION_STRING

    telemetry_status["connection_string"] = bool(connection_string)
    telemetry_status["enabled"] = False
    telemetry_status["initialized"] = False
    telemetry_status["error"] = None

    if not connection_string:
        telemetry_status["error"] = "missing connection string"
        logger.info("Azure Application Insights disabled: no connection string configured.")
        return

    if AzureMonitorTraceExporter is None:
        telemetry_status["error"] = "exporter package not installed"
        logger.warning(
            "Azure Application Insights exporter package is not installed. "
            "Install 'azure-monitor-opentelemetry-exporter' and restart the app."
        )
        return

    try:
        resource = Resource.create(
            {
                "service.name": settings.APP_NAME,
                "service.version": settings.APP_VERSION,
            }
        )

        provider = TracerProvider(resource=resource)
        exporter = AzureMonitorTraceExporter(connection_string=connection_string)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        RequestsInstrumentor().instrument()
        LoggingInstrumentor().instrument(set_logging_format=True)

        telemetry_status["initialized"] = True
        telemetry_status["enabled"] = True
        logger.info("Azure Application Insights telemetry initialized.")
        logger.info("Azure Application Insights is configured and log messages should be forwarded.")
    except Exception as exc:
        telemetry_status["error"] = str(exc)
        logger.warning(f"Failed to initialize Azure Application Insights telemetry: {exc}")
