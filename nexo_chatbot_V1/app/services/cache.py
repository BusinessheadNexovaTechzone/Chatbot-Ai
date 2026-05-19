import redis.asyncio as aioredis
import json
import hashlib
from typing import Optional, Any
from app.config.settings import get_settings
from app.utils.logger import logger

settings = get_settings()

class CacheService:
    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def connect(self):
        self._client = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Redis connected")

    async def disconnect(self):
        if self._client:
            await self._client.aclose()

    def _make_key(self, prefix: str, query: str) -> str:
        digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
        return f"chatbot:{prefix}:{digest}"

    async def get(self, prefix: str, query: str) -> Optional[Any]:
        if not self._client:
            return None
        key = self._make_key(prefix, query)
        try:
            value = await self._client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
        return None

    async def set(self, prefix: str, query: str, value: Any, ttl: int = None) -> bool:
        if not self._client:
            return False
        key = self._make_key(prefix, query)
        ttl = ttl or settings.CACHE_TTL_SECONDS
        try:
            await self._client.setex(key, ttl, json.dumps(value))
            logger.debug(f"Cache SET: {key}")
            return True
        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return False

    async def delete(self, prefix: str, query: str) -> bool:
        if not self._client:
            return False
        key = self._make_key(prefix, query)
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
            return False

    async def ping(self) -> bool:
        try:
            if self._client:
                await self._client.ping()
                return True
        except Exception:
            pass
        return False

cache_service = CacheService()
