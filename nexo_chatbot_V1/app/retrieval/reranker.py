from typing import List, Dict, Optional
import asyncio
from app.models.schemas import DocumentChunk
from app.config.settings import get_settings
from app.utils.logger import logger
import numpy as np

settings = get_settings()

class Reranker:
    """
    Advanced cross-encoder reranker with multi-signal scoring.
    Combines:
    - Vector search scores (similarity)
    - BM25 keyword matching scores
    - Cross-encoder semantic relevance scores
    
    Uses sentence-transformers cross-encoder if available,
    otherwise falls back to combined vector + BM25 scoring.
    """
    def __init__(self):
        self._model = None
        self._available = False
        # Weighting for combined scoring
        self.weights = {
            "vector_score": 0.4,      # Vector similarity
            "bm25_score": 0.3,        # BM25 keyword match
            "cross_encoder": 0.3      # Semantic relevance (when available)
        }

    def _load_model(self):
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            self._available = True
            logger.info("Cross-encoder reranker loaded")
        except ImportError:
            logger.warning("sentence-transformers not installed — using hybrid scoring instead")
            self._available = False

    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """Normalize scores to [0, 1] range for fair comparison."""
        if not scores:
            return []
        
        arr = np.array(scores)
        min_score = np.min(arr)
        max_score = np.max(arr)
        
        if max_score == min_score:
            return [0.5] * len(scores)
        
        normalized = (arr - min_score) / (max_score - min_score)
        return normalized.tolist()

    def _compute_hybrid_score(
        self,
        vector_score: float,
        bm25_score: float = 0.0,
        cross_encoder_score: float = 0.0
    ) -> float:
        """
        Compute combined score from multiple signals.
        All input scores should be normalized to [0, 1].
        """
        score = (
            self.weights["vector_score"] * vector_score +
            self.weights["bm25_score"] * bm25_score +
            self.weights["cross_encoder"] * cross_encoder_score
        )
        return float(score)

    def incorporate_bm25_scores(
        self,
        chunks: List[DocumentChunk],
        bm25_results: List[tuple]
    ) -> List[DocumentChunk]:
        """
        Incorporate BM25 scores into chunks.
        bm25_results: List of (DocumentChunk, bm25_score) tuples from BM25 search.
        """
        # Create BM25 score map
        bm25_map = {}
        for chunk, bm25_score in bm25_results:
            chunk_content = chunk.content
            bm25_map[chunk_content] = bm25_score
        
        # Add BM25 scores to chunks
        for chunk in chunks:
            if chunk.content in bm25_map:
                chunk.bm25_score = bm25_map[chunk.content]
            else:
                chunk.bm25_score = 0.0
        
        return chunks

    async def rerank(
        self,
        query: str,
        chunks: List[DocumentChunk],
        top_n: int = None,
        use_cross_encoder: bool = True,
        use_hybrid: bool = True
    ) -> List[DocumentChunk]:
        """
        Rerank chunks using cross-encoder or hybrid scoring.
        
        Args:
            query: The search query
            chunks: List of DocumentChunk objects to rerank
            top_n: Number of top results to return
            use_cross_encoder: Whether to use cross-encoder if available
            use_hybrid: Whether to use hybrid scoring (combining multiple signals)
        
        Returns:
            Reranked list of chunks
        """
        top_n = top_n or settings.RERANK_TOP_N
        if not chunks:
            return chunks
        if len(chunks) <= top_n:
            return chunks

        # Load model if needed
        if use_cross_encoder and not self._available:
            self._load_model()

        if use_cross_encoder and self._available:
            # Use cross-encoder reranking
            loop = asyncio.get_event_loop()
            pairs = [[query, chunk.content] for chunk in chunks]
            ce_scores = await loop.run_in_executor(
                None, lambda: self._model.predict(pairs).tolist()
            )
            
            if use_hybrid and any(hasattr(chunk, 'bm25_score') for chunk in chunks):
                # Combine with BM25 and vector scores
                vector_scores = [getattr(chunk, 'score', 0.0) for chunk in chunks]
                bm25_scores = [getattr(chunk, 'bm25_score', 0.0) for chunk in chunks]
                
                # Normalize all scores
                vector_scores_norm = self._normalize_scores(vector_scores)
                bm25_scores_norm = self._normalize_scores(bm25_scores)
                ce_scores_norm = self._normalize_scores(ce_scores)
                
                # Compute hybrid scores
                for chunk, vs, bs, cs in zip(chunks, vector_scores_norm, bm25_scores_norm, ce_scores_norm):
                    chunk.score = self._compute_hybrid_score(vs, bs, cs)
                    # Store individual scores for debugging
                    chunk.vector_score = float(vs)
                    chunk.bm25_score = float(bs)
                    chunk.cross_encoder_score = float(cs)
            else:
                # Use only cross-encoder scores
                for chunk, score in zip(chunks, ce_scores):
                    chunk.score = float(score)
                    chunk.cross_encoder_score = float(score)
        
        elif use_hybrid:
            # Use hybrid scoring without cross-encoder
            vector_scores = [getattr(chunk, 'score', 0.0) for chunk in chunks]
            bm25_scores = [getattr(chunk, 'bm25_score', 0.0) for chunk in chunks]
            
            # Normalize scores
            vector_scores_norm = self._normalize_scores(vector_scores)
            bm25_scores_norm = self._normalize_scores(bm25_scores)
            
            # Adjust weights when cross-encoder not available
            adjusted_weights = {
                "vector_score": 0.5,
                "bm25_score": 0.5,
                "cross_encoder": 0.0
            }
            
            # Compute hybrid scores
            for chunk, vs, bs in zip(chunks, vector_scores_norm, bm25_scores_norm):
                chunk.score = (
                    adjusted_weights["vector_score"] * vs +
                    adjusted_weights["bm25_score"] * bs
                )
                chunk.vector_score = float(vs)
                chunk.bm25_score = float(bs)

        # Sort and return top_n
        reranked = sorted(chunks, key=lambda x: x.score, reverse=True)
        
        logger.debug(
            f"Reranked {len(chunks)} chunks → top {top_n}",
            extra={
                "top_score": reranked[0].score if reranked else 0,
                "cross_encoder_used": self._available and use_cross_encoder
            }
        )
        
        return reranked[:top_n]

    def set_weights(self, weights: Dict[str, float]):
        """
        Set custom weights for scoring components.
        Weights should sum to 1.0.
        """
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Weights sum to {total}, not 1.0. Normalizing...")
            weights = {k: v / total for k, v in weights.items()}
        
        self.weights = weights
        logger.info(f"Reranker weights updated: {self.weights}")


reranker = Reranker()
