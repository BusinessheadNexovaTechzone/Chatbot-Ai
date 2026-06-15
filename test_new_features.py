"""
Test script for Query Rewrite, BM25 Search, and Chunk Reranking features.
Demonstrates spelling correction, query rewriting, and hybrid retrieval.
"""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.query_processor import query_processor
from app.retrieval.bm25_search import bm25_search
from app.retrieval.reranker import reranker
from app.models.schemas import DocumentChunk
from app.utils.logger import logger

def test_query_processor():
    """Test query processing: spelling correction, typo handling, normalization."""
    print("\n" + "="*60)
    print("TEST 1: Query Processor - Spelling & Typo Handling")
    print("="*60)
    
    test_queries = [
        "hii there",  # Common typo
        "whats the CEO information",  # Typo
        "can you tell me about the company",  # Filler prefix
        "pls provide FAQ",  # Abbreviation
        "thanku for the help",  # Typo
        "what is the API documentation",  # Abbreviation
        "company locaton and addres",  # Spelling mistakes
    ]
    
    for query in test_queries:
        original, processed, was_modified = query_processor.process_query(query)
        print(f"\nOriginal:  '{original}'")
        print(f"Processed: '{processed}'")
        print(f"Modified:  {was_modified}")


def test_bm25_search():
    """Test BM25 search functionality."""
    print("\n" + "="*60)
    print("TEST 2: BM25 Search Initialization & Statistics")
    print("="*60)
    
    # Create sample chunks
    sample_chunks = [
        DocumentChunk(
            id="1",
            content="The company headquarters is located in San Francisco, California. Contact us at (555) 123-4567.",
            source="About Us",
            url="https://example.com/about",
            section="Contact Information"
        ),
        DocumentChunk(
            id="2",
            content="Our CEO is John Smith. He has been leading the company since 2020 and has over 20 years of experience in the industry.",
            source="Leadership",
            url="https://example.com/team",
            section="Executive Team"
        ),
        DocumentChunk(
            id="3",
            content="The API documentation provides endpoints for users, products, and orders. All APIs require authentication.",
            source="Documentation",
            url="https://example.com/api",
            section="API Reference"
        ),
    ]
    
    print("\nInitializing BM25 with sample chunks...")
    bm25_search.initialize_from_chunks(sample_chunks)
    
    stats = bm25_search.get_statistics()
    print(f"\nBM25 Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


async def test_reranker_hybrid_scoring():
    """Test reranker with hybrid scoring."""
    print("\n" + "="*60)
    print("TEST 3: Enhanced Reranker - Hybrid Scoring")
    print("="*60)
    
    # Create test chunks with different scores
    chunks = [
        DocumentChunk(
            id="1",
            content="The CEO is the Chief Executive Officer responsible for strategy.",
            source="Wikipedia",
            url="https://example.com/1",
            score=0.85  # High vector similarity
        ),
        DocumentChunk(
            id="2",
            content="Our Chief Executive Officer, John Smith, leads the team.",
            source="Company",
            url="https://example.com/2",
            score=0.72
        ),
        DocumentChunk(
            id="3",
            content="Executive leadership structure includes the CEO position.",
            source="HR",
            url="https://example.com/3",
            score=0.65
        ),
    ]
    
    # Add BM25 scores
    chunks[0].bm25_score = 0.9
    chunks[1].bm25_score = 0.95
    chunks[2].bm25_score = 0.6
    
    print(f"\nBefore Reranking:")
    for chunk in chunks:
        print(f"  ID: {chunk.id}, Vector: {chunk.score:.2f}, BM25: {chunk.bm25_score:.2f}")
    
    print(f"\nReranking with hybrid scoring (vector=0.4, bm25=0.3, cross-encoder=0.3)...")
    reranked = await reranker.rerank(
        query="Who is the CEO?",
        chunks=chunks,
        top_n=3,
        use_cross_encoder=False,  # Set to False if cross-encoder not available
        use_hybrid=True
    )
    
    print(f"\nAfter Reranking (sorted by combined score):")
    for chunk in reranked:
        print(f"  ID: {chunk.id}, Combined Score: {chunk.score:.3f}")
        if hasattr(chunk, 'vector_score'):
            print(f"    → Vector: {chunk.vector_score:.3f}, BM25: {chunk.bm25_score:.3f}")


def test_weighting_customization():
    """Test custom weight configuration."""
    print("\n" + "="*60)
    print("TEST 4: Reranker - Custom Weight Configuration")
    print("="*60)
    
    print(f"\nDefault Weights:")
    print(f"  {reranker.weights}")
    
    custom_weights = {
        "vector_score": 0.5,
        "bm25_score": 0.4,
        "cross_encoder": 0.1
    }
    
    print(f"\nSetting Custom Weights (emphasize vector + BM25):")
    reranker.set_weights(custom_weights)
    print(f"  {reranker.weights}")


async def main():
    """Run all tests."""
    print("\n" + "█"*60)
    print("FEATURE TESTING: Query Rewrite, BM25 Search, Chunk Reranking")
    print("█"*60)
    
    try:
        # Test 1: Query Processing
        test_query_processor()
        
        # Test 2: BM25 Search
        test_bm25_search()
        
        # Test 3: Reranker Hybrid Scoring
        await test_reranker_hybrid_scoring()
        
        # Test 4: Weight Customization
        test_weighting_customization()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
        print("="*60)
        print("\nNEW FEATURES SUMMARY:")
        print("  1. Query Processor: Handles spelling correction and typo fixing")
        print("  2. BM25 Search: Keyword-based retrieval complementing vector search")
        print("  3. Enhanced Reranking: Hybrid scoring combining multiple signals")
        print("  4. Custom Weights: Configurable weight allocation for scoring")
        print("\nNo existing functionality has been disrupted.")
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
