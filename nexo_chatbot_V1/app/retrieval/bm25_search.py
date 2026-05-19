"""
BM25 Search Module: Traditional keyword-based search complement to vector search.
Provides better recall for exact keyword matches and domain-specific terminology.
"""

from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
from app.models.schemas import DocumentChunk
from app.utils.logger import logger
import asyncio

class BM25Search:
    """
    BM25 (Best Matching 25) implementation using rank_bm25.
    Complements vector search for better retrieval of documents with exact keyword matches.
    """
    
    def __init__(self):
        self.bm25_model = None
        self.chunks_corpus = []  # List of (chunk_id, content) tuples
        self.chunk_map = {}  # Map chunk_id -> DocumentChunk
        self.is_initialized = False
    
    def initialize_from_chunks(self, chunks: List[DocumentChunk]):
        """
        Initialize BM25 model from a list of document chunks.
        Called when chunks are indexed or during system startup.
        """
        if not chunks:
            logger.warning("No chunks provided for BM25 initialization")
            return
        
        try:
            # Tokenize documents for BM25
            corpus = []
            self.chunks_corpus = []
            self.chunk_map = {}
            
            for chunk in chunks:
                # Tokenize: split by whitespace and convert to lowercase
                tokens = chunk.content.lower().split()
                corpus.append(tokens)
                
                chunk_id = getattr(chunk, 'id', str(hash(chunk.content)))
                self.chunks_corpus.append((chunk_id, chunk.content))
                self.chunk_map[chunk_id] = chunk
            
            # Initialize BM25 model
            self.bm25_model = BM25Okapi(corpus)
            self.is_initialized = True
            
            logger.info(f"BM25 model initialized with {len(chunks)} chunks")
        except Exception as e:
            logger.error(f"Failed to initialize BM25 model: {e}")
            self.is_initialized = False
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.1
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Perform BM25 search on indexed chunks.
        Returns list of (DocumentChunk, BM25_score) tuples, sorted by score descending.
        
        Args:
            query: Search query string
            top_k: Number of top results to return
            min_score: Minimum BM25 score threshold
        
        Returns:
            List of (DocumentChunk, score) tuples
        """
        if not self.is_initialized or not self.bm25_model:
            logger.warning("BM25 model not initialized. Run on event loop executor.")
            return []
        
        try:
            # Tokenize query
            query_tokens = query.lower().split()
            
            # Run BM25 search in executor to avoid blocking
            loop = asyncio.get_event_loop()
            scores = await loop.run_in_executor(
                None,
                self.bm25_model.get_scores,
                query_tokens
            )
            
            # Create result list with scores
            results = []
            for idx, score in enumerate(scores):
                if score >= min_score and idx < len(self.chunks_corpus):
                    chunk_id, _ = self.chunks_corpus[idx]
                    chunk = self.chunk_map.get(chunk_id)
                    if chunk:
                        results.append((chunk, float(score)))
            
            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            
            # Return top_k
            return results[:top_k]
        
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []
    
    def update_chunks(self, chunks: List[DocumentChunk]):
        """
        Update BM25 model with new/modified chunks.
        Should be called when documents are added or updated.
        """
        self.initialize_from_chunks(chunks)

    def clear(self):
        """Clear all BM25 indexed chunks."""
        self.bm25_model = None
        self.chunks_corpus = []
        self.chunk_map = {}
        self.is_initialized = False
        logger.info("Cleared BM25 index and chunk cache")

    def get_statistics(self) -> Dict:
        """Get BM25 model statistics."""
        return {
            "initialized": self.is_initialized,
            "indexed_chunks": len(self.chunks_corpus),
            "model_type": "BM25Okapi",
            "corpus_size": len(self.chunks_corpus) if self.bm25_model else 0
        }


# Singleton instance
bm25_search = BM25Search()
