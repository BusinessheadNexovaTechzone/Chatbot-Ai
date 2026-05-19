import re
import asyncio
from typing import List, Optional, Dict, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, SearchRequest, ScoredPoint, PayloadSchemaType,
    TextIndexParams, TokenizerType
)
import uuid
from app.config.settings import get_settings
from app.models.schemas import DocumentChunk
from app.retrieval.embeddings import embedding_service
from app.utils.logger import logger

settings = get_settings()

class VectorStore:
    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None

    async def connect(self):
        """Connect to Qdrant with retry logic."""
        if self._client:
            return  # Already connected

    async def connect(self):
        """Connect to Qdrant with minimal retry logic."""
        if self._client:
            return  # Already connected

        try:
            if settings.QDRANT_URL:
                self._client = AsyncQdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=3.0,
                    check_compatibility=False,
                )
                endpoint_desc = settings.QDRANT_URL
            elif settings.QDRANT_HOST.startswith(("http://", "https://")):
                self._client = AsyncQdrantClient(
                    url=settings.QDRANT_HOST,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=3.0,
                    check_compatibility=False,
                )
                endpoint_desc = settings.QDRANT_HOST
            else:
                self._client = AsyncQdrantClient(
                    host=settings.QDRANT_HOST,
                    port=settings.QDRANT_PORT,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=3.0,
                    check_compatibility=False,
                )
                endpoint_desc = f"{settings.QDRANT_HOST}:{settings.QDRANT_PORT}"
            
            await self._ensure_collection()
            logger.info(f"Qdrant connected: {endpoint_desc}")
        except Exception as e:
            logger.warning(f"Qdrant connection failed: {e}")
            self._client = None

    async def is_connected(self) -> bool:
        """Check if vector store is connected and available."""
        if not self._client:
            # Try to connect
            await self.connect()
            if not self._client:
                return False
        try:
            await self._client.get_collections()
            return True
        except Exception:
            self._client = None
            return False

    async def disconnect(self):
        if self._client:
            await self._client.close()

    async def _ensure_collection(self):
        collections = await self._client.get_collections()
        names = [c.name for c in collections.collections]
        if settings.QDRANT_COLLECTION in names:
            collection_info = await self._client.get_collection(settings.QDRANT_COLLECTION)
            current_dim = collection_info.config.params.vectors.size
            if current_dim != settings.EMBEDDING_DIM:
                await self._client.delete_collection(settings.QDRANT_COLLECTION)
                logger.info(f"Deleted collection {settings.QDRANT_COLLECTION} due to dim mismatch: {current_dim} != {settings.EMBEDDING_DIM}")
                names.remove(settings.QDRANT_COLLECTION)
        if settings.QDRANT_COLLECTION not in names:
            await self._client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            # Create payload index for hybrid search on content
            await self._client.create_payload_index(
                collection_name=settings.QDRANT_COLLECTION,
                field_name="content",
                field_schema=TextIndexParams(
                    type="text",
                    tokenizer=TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                ),
            )
            logger.info(f"Created Qdrant collection: {settings.QDRANT_COLLECTION}")

    async def upsert_chunks(self, chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
        """Upsert chunks to vector store with error handling."""
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping chunk indexing for speed.")
            return  # Skip instead of failing

        points = []
        document_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "content": chunk["content"],
                    "source": chunk["source"],
                    "url": chunk["url"],
                    "section": chunk.get("section", ""),
                    "timestamp": chunk.get("timestamp", ""),
                },
            )
            points.append(point)
            
            # Also create DocumentChunk for BM25 initialization
            doc_chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                content=chunk["content"],
                source=chunk["source"],
                url=chunk["url"],
                section=chunk.get("section", ""),
                timestamp=chunk.get("timestamp", ""),
            )
            document_chunks.append(doc_chunk)

        try:
            await self._client.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
            )
            logger.info(f"Upserted {len(points)} chunks to Qdrant")
            
            # ✅ NEW: Update BM25 search with new chunks
            try:
                from app.retrieval.bm25_search import bm25_search
                bm25_search.update_chunks(document_chunks)
                logger.info(f"Updated BM25 index with {len(document_chunks)} chunks")
            except Exception as bm25_err:
                logger.warning(f"Failed to update BM25 index (non-blocking): {bm25_err}")
        
        except Exception as e:
            logger.warning(f"Failed to upsert chunks (non-blocking): {e}")
            # Don't raise exception - allow upload to succeed without vector storage

    async def search(
        self,
        query_vector: List[float],
        top_k: int = None,
        source_filter: Optional[str] = None,
        score_threshold: Optional[float] = None,
    ) -> List[DocumentChunk]:
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping retrieval for speed.")
            return []  # Return empty results instead of failing

        top_k = top_k or settings.TOP_K
        query_filter = None
        if source_filter:
            query_filter = Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source_filter))]
            )

        query_kwargs: Dict[str, Any] = {
            "collection_name": settings.QDRANT_COLLECTION,
            "query": query_vector,
            "query_filter": query_filter,
            "limit": top_k,
            "with_payload": True,
        }
        if score_threshold is not None:
            query_kwargs["score_threshold"] = score_threshold

        response = await self._client.query_points(**query_kwargs)
        results = response.points
        logger.info(f"Vector search returned {len(results)} points")

        return [
            DocumentChunk(
                id=str(r.id),
                content=r.payload.get("content", ""),
                source=r.payload.get("source", ""),
                url=r.payload.get("url", ""),
                section=r.payload.get("section"),
                timestamp=r.payload.get("timestamp"),
                score=r.score,
            )
            for r in results
        ]

    async def search_with_text(self, query: str, query_vector: List[float], top_k: int = None) -> List[DocumentChunk]:
        """Hybrid search: combine vector similarity with keyword overlap and text fallback."""
        top_k = top_k or settings.TOP_K

        # First try direct keyword search for specific queries
        keyword_results = await self._keyword_only_search(query, top_k)
        if keyword_results and keyword_results[0].score > 0.1:  # If we have good keyword matches
            return keyword_results[:top_k]

        # Semantic search, keep low threshold for broad recall
        semantic_results = await self.search(
            query_vector=query_vector,
            top_k=top_k * 2,
            score_threshold=None,
        )

        if not semantic_results:
            return await self._keyword_only_search(query, top_k)

        # Score fusion: boost results where query keywords appear in content or section
        query_words = set(re.findall(r"\w+", query.lower()))
        for chunk in semantic_results:
            content_words = set(re.findall(r"\w+", chunk.content.lower()))
            section_words = set(re.findall(r"\w+", (chunk.section or "").lower()))

            # Keyword overlap with content
            content_overlap = len(query_words & content_words) / max(len(query_words), 1)

            # Section name match (higher weight if section matches query)
            section_match = len(query_words & section_words) / max(len(query_words), 1)

            # Fused score: section match gets 40%, content overlap gets 30%, semantic gets 30%
            chunk.score = (
                chunk.score * 0.3 +
                content_overlap * 0.3 +
                section_match * 0.4
            )

        # Re-sort by fused score
        semantic_results.sort(key=lambda x: x.score, reverse=True)
        return semantic_results[:top_k]

    async def _keyword_only_search(self, query: str, top_k: int) -> List[DocumentChunk]:
        """Fallback search using keyword overlap against stored content and section payload."""
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping keyword search for speed.")
            return []

        query_words = set(re.findall(r"\w+", query.lower()))
        if not query_words:
            return []

        try:
            scroll_result = await self._client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                limit=1000,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning(f"Keyword fallback scroll failed: {exc}")
            return []

        candidates: List[DocumentChunk] = []
        for point in scroll_result[0]:
            content = (point.payload or {}).get("content", "")
            section = (point.payload or {}).get("section", "")
            
            content_words = set(re.findall(r"\w+", content.lower()))
            section_words = set(re.findall(r"\w+", section.lower()))
            
            # Calculate overlap scores
            content_overlap = len(query_words & content_words) / max(len(query_words), 1)
            section_overlap = len(query_words & section_words) / max(len(query_words), 1)
            
            # Combined score: section match gets higher priority
            combined_score = content_overlap * 0.4 + section_overlap * 0.6
            
            if combined_score > 0:
                candidates.append(DocumentChunk(
                    id=str(point.id),
                    content=content,
                    source=(point.payload or {}).get("source", ""),
                    url=(point.payload or {}).get("url", ""),
                    section=section,
                    timestamp=(point.payload or {}).get("timestamp", ""),
                    score=combined_score,
                ))

        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:top_k]

    async def clear_collection(self) -> bool:
        """Delete and recreate the configured Qdrant collection to clear all uploaded documents."""
        if not await self.is_connected():
            logger.warning("Vector store not connected; cannot clear collection.")
            return False

        try:
            await self._client.delete_collection(collection_name=settings.QDRANT_COLLECTION)
            logger.info(f"Cleared Qdrant collection: {settings.QDRANT_COLLECTION}")
            self._client = None
            await self.connect()
            return True
        except Exception as e:
            logger.warning(f"Failed to clear Qdrant collection: {e}")
            return False

    async def ping(self) -> bool:
        try:
            if self._client:
                await self._client.get_collections()
                return True
        except Exception:
            pass
        return False

vector_store = VectorStore()
