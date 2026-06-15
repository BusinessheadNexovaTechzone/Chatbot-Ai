import json
import os
import re
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any

import numpy as np
import uuid
from turbovec import IdMapIndex

from app.config.settings import get_settings
from app.services.telemetry import (
    record_keyword_cache_hit,
    record_keyword_cache_miss,
    record_timing,
)
from app.models.schemas import DocumentChunk
from app.retrieval.embeddings import embedding_service
from app.utils.logger import logger

settings = get_settings()

class TurboVecBackend:
    def __init__(self):
        self._index: Optional[IdMapIndex] = None
        self._payloads: Dict[int, Dict[str, Any]] = {}
        self._next_id: int = 1
        self._index_path = settings.TURBOVEC_INDEX_PATH
        self._payload_path = settings.TURBOVEC_PAYLOAD_PATH
        self._dim = settings.EMBEDDING_DIM
        self._bit_width = settings.TURBOVEC_BIT_WIDTH
        # Simple in-memory TTL cache for keyword-only searches to reduce repeated work
        self._keyword_cache: Dict[str, tuple[float, List[DocumentChunk]]] = {}
        self._keyword_cache_ttl = getattr(settings, "TURBOVEC_KEYWORD_CACHE_TTL_SECONDS", 300)

    def _ensure_paths(self):
        directory = Path(self._index_path).parent
        if directory and not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)

    def connect(self):
        self._ensure_paths()
        if self._index is not None:
            return
        if Path(self._index_path).exists():
            try:
                self._index = IdMapIndex.load(self._index_path)
                logger.info(f"TurboVec loaded index from {self._index_path}")
            except Exception as exc:
                logger.warning(f"Failed to load TurboVec index, creating new one: {exc}")
                self._index = IdMapIndex(dim=self._dim, bit_width=self._bit_width)
        else:
            self._index = IdMapIndex(dim=self._dim, bit_width=self._bit_width)
            logger.info(f"TurboVec created new index at dim={self._dim}, bit_width={self._bit_width}")

        self._load_payloads()
        if self._payloads:
            self._next_id = max(self._payloads.keys(), default=0) + 1

    def _load_payloads(self):
        if Path(self._payload_path).exists():
            try:
                with open(self._payload_path, "r", encoding="utf-8") as fp:
                    raw = json.load(fp)
                self._payloads = {int(k): v for k, v in raw.items()}
            except Exception as exc:
                logger.warning(f"Failed to load TurboVec payloads: {exc}")
                self._payloads = {}
        else:
            self._payloads = {}

    def _save_payloads(self):
        try:
            with open(self._payload_path, "w", encoding="utf-8") as fp:
                json.dump({str(k): v for k, v in self._payloads.items()}, fp)
        except Exception as exc:
            logger.warning(f"Failed to save TurboVec payloads: {exc}")

    def save(self):
        if self._index is not None:
            try:
                self._index.write(self._index_path)
            except Exception as exc:
                logger.warning(f"Failed to write TurboVec index: {exc}")
        self._save_payloads()

    def add_vectors(self, chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
        if self._index is None:
            self.connect()
        if not embeddings:
            return

        n = len(embeddings)
        ids = np.arange(self._next_id, self._next_id + n, dtype=np.uint64)
        self._next_id += n
        vectors = np.asarray(embeddings, dtype=np.float32)

        try:
            self._index.add_with_ids(vectors, ids)
        except Exception as exc:
            logger.warning(f"TurboVec add_with_ids failed: {exc}")
            return

        for doc_id, chunk in zip(ids.tolist(), chunks):
            self._payloads[int(doc_id)] = {
                "content": chunk["content"],
                "source": chunk["source"],
                "url": chunk["url"],
                "section": chunk.get("section", ""),
                "timestamp": chunk.get("timestamp", ""),
            }

        self.save()

    def search(
        self,
        query_vector: List[float],
        top_k: int = None,
        k: int = None,
        allowlist: Optional[np.ndarray] = None,
    ):
        if top_k is None:
            top_k = k or 10
        if self._index is None:
            self.connect()
        q = np.asarray(query_vector, dtype=np.float32)
        if q.ndim == 1:
            q = np.expand_dims(q, axis=0)

        if allowlist is not None:
            allowlist = np.asarray(allowlist, dtype=np.uint64)

        try:
            scores, ids = self._index.search(q, k=top_k, allowlist=allowlist)
        except Exception as exc:
            logger.warning(f"TurboVec search failed: {exc}")
            return []

        scores = np.asarray(scores)
        ids = np.asarray(ids)
        if scores.ndim == 2:
            scores = scores[0]
        if ids.ndim == 2:
            ids = ids[0]

        results: List[DocumentChunk] = []
        for score, doc_id in zip(scores.tolist(), ids.tolist()):
            payload = self._payloads.get(int(doc_id))
            if not payload:
                continue
            results.append(DocumentChunk(
                id=str(int(doc_id)),
                content=payload.get("content", ""),
                source=payload.get("source", ""),
                url=payload.get("url", ""),
                section=payload.get("section", ""),
                timestamp=payload.get("timestamp", ""),
                score=float(score),
            ))
        return results

    def _keyword_only_search(self, query: str, top_k: int):
        # Check TTL cache first
        import time as _time
        now = _time.time()
        cache_key = f"kw:{query.lower().strip()}:{top_k}"
        cached = self._keyword_cache.get(cache_key)
        if cached:
            ts, results = cached
            if now - ts < self._keyword_cache_ttl:
                logger.info(f"TurboVec keyword cache HIT for query='{query[:80]}'")
                try:
                    record_keyword_cache_hit()
                except Exception:
                    pass
                return results
            else:
                try:
                    del self._keyword_cache[cache_key]
                except KeyError:
                    pass
        query_words = set(re.findall(r"\w+", query.lower()))
        if not query_words:
            return []

        candidates: List[DocumentChunk] = []
        for doc_id, payload in self._payloads.items():
            content_words = set(re.findall(r"\w+", payload.get("content", "").lower()))
            section_words = set(re.findall(r"\w+", payload.get("section", "").lower()))
            content_overlap = len(query_words & content_words) / max(len(query_words), 1)
            section_overlap = len(query_words & section_words) / max(len(query_words), 1)
            combined_score = content_overlap * 0.4 + section_overlap * 0.6
            if combined_score > 0:
                candidates.append(DocumentChunk(
                    id=str(doc_id),
                    content=payload.get("content", ""),
                    source=payload.get("source", ""),
                    url=payload.get("url", ""),
                    section=payload.get("section", ""),
                    timestamp=payload.get("timestamp", ""),
                    score=combined_score,
                ))

        start = _time.perf_counter()
        candidates.sort(key=lambda x: x.score, reverse=True)
        out = candidates[:top_k]
        try:
            # store a shallow copy to avoid accidental mutation
            self._keyword_cache[cache_key] = (now, list(out))
            try:
                record_keyword_cache_miss()
            except Exception:
                pass
        except Exception:
            pass
        elapsed_ms = ( _time.perf_counter() - start ) * 1000.0
        try:
            record_timing("turbovec_keyword_search_ms", elapsed_ms)
        except Exception:
            pass
        return out

    def clear(self):
        self._index = IdMapIndex(dim=self._dim, bit_width=self._bit_width)
        self._payloads = {}
        self._next_id = 1
        try:
            if Path(self._index_path).exists():
                Path(self._index_path).unlink()
            if Path(self._payload_path).exists():
                Path(self._payload_path).unlink()
        except Exception as exc:
            logger.warning(f"Failed to clear TurboVec files: {exc}")

    def ping(self) -> bool:
        return self._index is not None or Path(self._index_path).exists()


class VectorStore:
    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None
        self._turbovec: Optional[TurboVecBackend] = None
        self._use_turbovec = settings.USE_TURBOVEC
        if self._use_turbovec:
            self._turbovec = TurboVecBackend()

    async def connect(self):
        if self._use_turbovec:
            self._turbovec.connect()
            return

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
        if self._use_turbovec:
            self._turbovec.connect()
            return True

        if not self._client:
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
        if self._use_turbovec:
            self._turbovec.save()
            return
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

        if self._use_turbovec:
            try:
                self._turbovec.add_vectors(chunks, embeddings)
                logger.info(f"Upserted {len(chunks)} chunks to TurboVec")
            except Exception as e:
                logger.warning(f"Failed to upsert chunks to TurboVec (non-blocking): {e}")
        else:
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
        k: int = None,
        source_filter: Optional[str] = None,
        score_threshold: Optional[float] = None,
        allowlist: Optional[np.ndarray] = None,
    ) -> List[DocumentChunk]:
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping retrieval for speed.")
            return []  # Return empty results instead of failing

        top_k = top_k or settings.TOP_K
        if self._use_turbovec:
            return await asyncio.to_thread(
                self._turbovec.search,
                query_vector,
                top_k,
                None,
                allowlist,
            )

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

    async def search_with_text(self, query: str, query_vector: List[float] = None, top_k: int = None) -> List[DocumentChunk]:
        """Hybrid search: combine vector similarity with keyword overlap and text fallback."""
        top_k = top_k or settings.TOP_K

        # First try direct keyword search for specific queries
        keyword_results = await self.keyword_search(query, top_k)
        if keyword_results and keyword_results[0].score > 0.1:  # If we have good keyword matches
            return keyword_results[:top_k]

        if query_vector is None:
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

    async def keyword_search(self, query: str, top_k: int) -> List[DocumentChunk]:
        """Fast keyword-only search using TurboVec payloads or Qdrant text scan."""
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping keyword search for speed.")
            return []

        if self._use_turbovec:
            return await asyncio.to_thread(self._turbovec._keyword_only_search, query, top_k)

        return await self._keyword_only_search(query, top_k)

    async def _keyword_only_search(self, query: str, top_k: int) -> List[DocumentChunk]:
        """Fallback search using keyword overlap against stored content and section payload."""
        if not await self.is_connected():
            logger.warning("Vector store not connected. Skipping keyword search for speed.")
            return []

        if self._use_turbovec:
            return await asyncio.to_thread(self._turbovec._keyword_only_search, query, top_k)

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
        """Clear all uploaded documents from the active vector store."""
        if not await self.is_connected():
            logger.warning("Vector store not connected; cannot clear collection.")
            return False

        if self._use_turbovec:
            try:
                self._turbovec.clear()
                logger.info("Cleared TurboVec local index")
                return True
            except Exception as e:
                logger.warning(f"Failed to clear TurboVec local index: {e}")
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
        if self._use_turbovec:
            return self._turbovec.ping()
        try:
            if self._client:
                await self._client.get_collections()
                return True
        except Exception:
            pass
        return False

vector_store = VectorStore()
