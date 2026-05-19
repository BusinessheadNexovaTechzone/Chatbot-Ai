import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.api.routes.chat import router as chat_router
from app.api.routes.websocket_chat import router as ws_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.upload import router as upload_router
from app.api.routes.whatsapp import router as whatsapp_router
from app.services.cache import cache_service
from app.services.mongodb import mongo_service
from app.services.queue import queue_service
from app.retrieval.vector_store import vector_store
from app.services.telemetry import get_telemetry_status, init_telemetry
from app.services.web_search import web_search_service
from app.models.schemas import HealthResponse
from app.utils.logger import logger

class VersionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-API-Version"] = settings.APP_VERSION
        return response

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} on port {settings.PORT}")
    
    # Initialize synchronous services
    try:
        queue_service.connect()
    except Exception as e:
        logger.warning(f"Redis Queue failed to connect: {e}")
    
    results = await asyncio.gather(
        cache_service.connect(),
        mongo_service.connect(),
        vector_store.connect(),
        web_search_service.connect(),
        return_exceptions=True,
    )
    for svc, result in zip(["redis", "mongodb", "qdrant", "web_search"], results):
        if isinstance(result, Exception):
            logger.warning(f"{svc} failed to connect: {result}")
    logger.info("All services initialized")
    yield
    await asyncio.gather(
        cache_service.disconnect(),
        mongo_service.disconnect(),
        vector_store.disconnect(),
        web_search_service.disconnect(),
        return_exceptions=True,
    )
    
    # Disconnect synchronous services
    queue_service.disconnect()
    
    logger.info("Shutdown complete")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

init_telemetry(app)

app.add_middleware(VersionMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(ingest_router)
app.include_router(upload_router)
app.include_router(whatsapp_router)

@app.get("/v1/health", response_model=HealthResponse)
async def health():
    redis_ok, mongo_ok, qdrant_ok = await asyncio.gather(
        cache_service.ping(),
        mongo_service.ping(),
        vector_store.ping(),
    )
    all_ok = redis_ok and mongo_ok and qdrant_ok
    return HealthResponse(
        status="healthy" if all_ok else "degraded",
        version=settings.APP_VERSION,
        components={
            "redis":   "ok" if redis_ok  else "unavailable",
            "mongodb": "ok" if mongo_ok  else "unavailable",
            "qdrant":  "ok" if qdrant_ok else "unavailable",
        },
    )

@app.get("/version")
async def get_version():
    """Get the current API version."""
    return {"version": settings.APP_VERSION}

@app.get("/telemetry-status")
async def telemetry_status():
    """Check whether Application Insights telemetry is configured and initialized."""
    return get_telemetry_status()
