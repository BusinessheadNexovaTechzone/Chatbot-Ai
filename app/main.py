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
from app.retrieval.embeddings import embedding_service
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
        # preload local embedding model to avoid first-call stall
        asyncio.to_thread(getattr(embedding_service, "_get_local_model", lambda: None)),
        web_search_service.connect(),
        return_exceptions=True,
    )
    for svc, result in zip(["redis", "mongodb", "vector_store", "web_search"], results):
        if isinstance(result, Exception):
            logger.warning(f"{svc} failed to connect: {result}")
    logger.info("All services initialized")
    # ✅ TurboVec warmup: run a small set of keyword queries to prime the in-memory payload cache and keyword TTL cache
    try:
        if settings.USE_TURBOVEC:
            warm_queries = getattr(settings, "TURBOVEC_WARM_QUERIES", []) or ["company", "products", "pricing", "contact", "address", "website"]
            logger.info(f"Running TurboVec warmup for {len(warm_queries)} queries")
            try:
                await asyncio.gather(*[vector_store.keyword_search(q, settings.TOP_K * 2) for q in warm_queries])
                logger.info("TurboVec warmup completed")
            except Exception as werr:
                logger.warning(f"TurboVec warmup failed: {werr}")
    except Exception:
        pass
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
    redis_ok, mongo_ok, vector_store_ok = await asyncio.gather(
        cache_service.ping(),
        mongo_service.ping(),
        vector_store.ping(),
    )
    all_ok = redis_ok and mongo_ok and vector_store_ok
    return HealthResponse(
        status="healthy" if all_ok else "degraded",
        version=settings.APP_VERSION,
        components={
            "redis":        "ok" if redis_ok        else "unavailable",
            "mongodb":      "ok" if mongo_ok        else "unavailable",
            "vector_store": "ok" if vector_store_ok else "unavailable",
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


@app.get("/v1/internal/telemetry")
async def telemetry_snapshot():
    """Return in-process telemetry counters and timings for debugging (non-sensitive)."""
    try:
        from app.services.telemetry import get_telemetry_snapshot
        return get_telemetry_snapshot()
    except Exception as e:
        logger.warning(f"Failed to get telemetry snapshot: {e}")
        return {"error": str(e)}
