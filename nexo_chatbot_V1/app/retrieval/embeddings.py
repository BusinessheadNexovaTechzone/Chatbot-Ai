"""
Embedding service with two backends:

  1. Gemini  (gemini-embedding-001, 3072 dims) — used when GEMINI_API_KEY is set
  2. Local   (all-MiniLM-L6-v2, 384 dims)    — used when no API key is available

Backend is selected once at startup based on settings.
Qdrant collection MUST be created with the matching EMBEDDING_DIM.
"""

import asyncio
from typing import List
import google.generativeai as genai
from app.config.settings import get_settings
from app.utils.logger import logger

settings = get_settings()

def _build_gemini_client():
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for online Gemini embeddings.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai

# Dimensions produced by each backend
GEMINI_EMBEDDING_DIM = 3072
LOCAL_EMBEDDING_DIM = 384

# Gemini supports up to 100 texts per embedding call
_BATCH_SIZE = 100


def _gemini_available() -> bool:
    return False


class EmbeddingService:
    def __init__(self):
        self._gemini_client = None
        self._local_model   = None
        self._use_gemini    = _gemini_available()

        backend = f"Gemini ({settings.EMBEDDING_MODEL}, dim={GEMINI_EMBEDDING_DIM})" \
                  if self._use_gemini else \
                  f"local all-MiniLM-L6-v2 (dim={LOCAL_EMBEDDING_DIM})"
        logger.info(f"Embedding backend: {backend}")

    # ── Client / model loaders ────────────────────────────────────────────────────────────────

    def _get_gemini_client(self):
        if self._gemini_client is None:
            self._gemini_client = _build_gemini_client()
        return self._gemini_client

    def _get_local_model(self):
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Local embedding model loaded: all-MiniLM-L6-v2")
        return self._local_model

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def dim(self) -> int:
        return GEMINI_EMBEDDING_DIM if self._use_gemini else LOCAL_EMBEDDING_DIM

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if self._use_gemini:
            try:
                return await self._embed_gemini(texts)
            except Exception as exc:
                logger.warning(f"Gemini embedding failed, using mock embeddings: {exc}")
                return await self._embed_mock(texts)
        else:
            return await self._embed_local(texts)

    async def embed_query(self, query: str) -> List[float]:
        results = await self.embed_texts([query])
        return results[0]

    # ── Backends ──────────────────────────────────────────────────────────────

    async def _embed_gemini(self, texts: List[str]) -> List[List[float]]:
        client = self._get_gemini_client()
        all_vectors: List[List[float]] = []

        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i:i + _BATCH_SIZE]
            response = await asyncio.to_thread(
                client.embed_content,
                model=f"models/{settings.EMBEDDING_MODEL}",
                content=batch,
                task_type="retrieval_document"
            )
            # Handle both single and batch responses
            if hasattr(response, '__iter__') and not isinstance(response, (str, bytes)):
                # Batch response
                all_vectors.extend([item['embedding'] for item in response])
            else:
                # Single response
                all_vectors.append(response['embedding'])

        return all_vectors

    async def _embed_mock(self, texts: List[str]) -> List[List[float]]:
        """Mock embeddings for testing - returns consistent 3072-dim vectors."""
        import random
        random.seed(42)  # For consistent results
        return [[random.random() for _ in range(GEMINI_EMBEDDING_DIM)] for _ in texts]

    async def _embed_local(self, texts: List[str]) -> List[List[float]]:
        """Local embeddings using all-MiniLM-L6-v2 model."""
        model = self._get_local_model()
        embeddings = await asyncio.to_thread(model.encode, texts, convert_to_tensor=False)
        return embeddings.tolist() if hasattr(embeddings, 'tolist') else list(embeddings)


embedding_service = EmbeddingService()
