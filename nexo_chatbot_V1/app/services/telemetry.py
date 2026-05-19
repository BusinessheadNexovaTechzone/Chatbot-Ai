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
