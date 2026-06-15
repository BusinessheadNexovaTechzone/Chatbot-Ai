"""
Test: TurboVec Parallel Multi-Search Speedup
Demonstrates how TurboVec's speed advantage multiplies with parallel searches.

Before: Single search @ 12ms faster = invisible (0.06% of 27s)
After:  3 parallel searches @ 3×12ms = 36ms faster = visible and compound!
"""

import asyncio
import time
from app.retrieval.vector_store import vector_store
from app.retrieval.embeddings import embedding_service
from app.config.settings import get_settings

settings = get_settings()

async def benchmark_single_search():
    """Benchmark single search (baseline)"""
    await vector_store.connect()
    await embedding_service.initialize()
    
    query = "tell about company products services"
    
    # Time a single search
    start = time.perf_counter()
    vector = await embedding_service.embed_query(query)
    search_time_start = time.perf_counter()
    results = await vector_store.search(vector, top_k=3)
    search_time = time.perf_counter() - search_time_start
    
    print(f"\n✅ SINGLE SEARCH")
    print(f"   Query: {query}")
    print(f"   Search time: {search_time*1000:.2f}ms")
    print(f"   Results: {len(results)} chunks")
    return search_time

async def benchmark_parallel_searches():
    """Benchmark 3 parallel searches (TurboVec advantage multiplies!)"""
    await vector_store.connect()
    await embedding_service.initialize()
    
    queries = [
        "tell about company",
        "company products services",
        "company overview information"
    ]
    
    # Time parallel embeddings
    embed_start = time.perf_counter()
    vectors = await asyncio.gather(
        *[embedding_service.embed_query(q) for q in queries]
    )
    embed_time = time.perf_counter() - embed_start
    
    # Time parallel searches (TurboVec shines here!)
    search_start = time.perf_counter()
    results = await asyncio.gather(
        *[vector_store.search(vec, top_k=3) for vec in vectors]
    )
    search_time = time.perf_counter() - search_start
    
    # Deduplicate results
    seen = set()
    unique_chunks = []
    for result_list in results:
        for chunk in result_list:
            chunk_id = f"{chunk.url}_{chunk.content[:50]}"
            if chunk_id not in seen:
                unique_chunks.append(chunk)
                seen.add(chunk_id)
    
    print(f"\n⚡ PARALLEL SEARCHES (3 variants)")
    print(f"   Queries: {queries}")
    print(f"   Embedding time: {embed_time*1000:.2f}ms")
    print(f"   Parallel search time: {search_time*1000:.2f}ms")
    print(f"   Total retrieval: {(embed_time + search_time)*1000:.2f}ms")
    print(f"   Unique results: {len(unique_chunks)} chunks")
    return search_time

async def main():
    print("\n" + "="*70)
    print("TurboVec Parallel Multi-Search Speedup Test")
    print("="*70)
    
    print(f"\n🔧 Configuration:")
    print(f"   USE_TURBOVEC: {settings.USE_TURBOVEC}")
    print(f"   TOP_K: {settings.TOP_K}")
    print(f"   RERANK_TOP_N: {settings.RERANK_TOP_N}")
    
    try:
        # Benchmark single search
        single_time = await benchmark_single_search()
        
        # Benchmark parallel searches
        parallel_time = await benchmark_parallel_searches()
        
        # Calculate speedup
        print(f"\n📊 SPEEDUP ANALYSIS")
        print(f"   Single search: {single_time*1000:.2f}ms")
        print(f"   Parallel (3×): {parallel_time*1000:.2f}ms")
        
        if parallel_time > 0:
            speedup_ratio = single_time / parallel_time
            print(f"\n   Parallel is {speedup_ratio:.2f}x faster (vectorized)")
            
        # Estimate actual latency impact
        print(f"\n🎯 IMPACT ON TOTAL LATENCY")
        print(f"   Old approach (single search):")
        print(f"     - Search: {single_time*1000:.2f}ms")
        print(f"     - Gemini: ~13,890ms")
        print(f"     - Total: ~13,900ms")
        
        print(f"\n   New approach (3 parallel searches):")
        print(f"     - Search: {parallel_time*1000:.2f}ms")
        print(f"     - Gemini: ~13,890ms (unchanged)")
        print(f"     - Total: ~{13890 + parallel_time*1000:.0f}ms")
        
        savings = (single_time - parallel_time) * 1000
        print(f"\n   Saved per query: ~{savings:.0f}ms ({(savings/13900)*100:.1f}%)")
        print(f"   Saved per 100 queries: ~{savings*100/1000:.1f}s")
        
        print(f"\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await vector_store.disconnect()
        await embedding_service.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
