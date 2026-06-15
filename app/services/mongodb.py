from datetime import datetime, timezone
from typing import Optional, List
import motor.motor_asyncio
from app.config.settings import get_settings
from app.utils.logger import logger

settings = get_settings()

class MongoService:
    def __init__(self):
        self._client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self._db = None

    async def connect(self):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URL)
        self._db = self._client[settings.MONGODB_DB]
        # Verify connection
        await self._client.admin.command("ping")
        logger.info(f"MongoDB connected: {settings.MONGODB_URL} / db={settings.MONGODB_DB}")

    async def disconnect(self):
        if self._client:
            self._client.close()

    def _col(self, name: str):
        return self._db[name]

    # ── Chat history ──────────────────────────────────────────────────────────

    async def save_chat(
        self,
        session_id: str,
        encrypted_query: str,
        encrypted_response: str,
        token_usage: Optional[dict] = None,
    ) -> str:
        doc = {
            "session_id": session_id,
            "query": encrypted_query,
            "response": encrypted_response,
            "token_usage": token_usage or {},
            "timestamp": datetime.now(timezone.utc),
        }
        result = await self._col("chat_history").insert_one(doc)
        return str(result.inserted_id)

    async def get_session_history(self, session_id: str, limit: int = 20) -> list:
        cursor = (
            self._col("chat_history")
            .find({"session_id": session_id}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def get_conversation_history(self, session_id: str, limit: int = 6) -> List[dict]:
        """
        Return the last `limit` turns as decrypted role/content pairs for LLM context.
        Returns: [{"role": "user"/"assistant", "content": "..."}] in chronological order.
        """
        if not session_id:
            return []
        try:
            from app.utils.encryption import decrypt
            from app.config.settings import get_settings
            key = get_settings().ENCRYPTION_KEY

            cursor = (
                self._col("chat_history")
                .find({"session_id": session_id}, {"_id": 0, "query": 1, "response": 1, "timestamp": 1})
                .sort("timestamp", -1)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
            # Reverse to chronological order
            docs = list(reversed(docs))

            history: List[dict] = []
            for doc in docs:
                try:
                    q = decrypt(doc["query"], key)
                    r = decrypt(doc["response"], key)
                    history.append({"role": "user",      "content": q})
                    history.append({"role": "assistant",  "content": r})
                except Exception as e:
                    logger.warning(f"Failed to decrypt history entry: {e}")
            return history
        except Exception as e:
            logger.warning(f"get_conversation_history failed: {e}")
            return []

    # ── Health ────────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        try:
            if self._client:
                await self._client.admin.command("ping")
                return True
        except Exception:
            pass
        return False

mongo_service = MongoService()
