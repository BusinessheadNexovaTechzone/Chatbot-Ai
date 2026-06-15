import asyncio
import time
from app.services.cache import cache_service
from app.retrieval.embeddings import embedding_service
from app.retrieval.vector_store import vector_store

async def main():
    await cache_service.connect()
    await vector_store.connect()
    q = "who is the ceo?"

    # First embed
    t0 = time.perf_counter()
    v1 = await embedding_service.embed_query(q)
    t1 = time.perf_counter()
    print(f"First embed: {(t1-t0)*1000:.2f} ms; len={len(v1)}")

    # Second embed (should hit cache)
    t0 = time.perf_counter()
    v2 = await embedding_service.embed_query(q)
    t1 = time.perf_counter()
    print(f"Second embed: {(t1-t0)*1000:.2f} ms; len={len(v2)}")

    # Search
    t0 = time.perf_counter()
    chunks = await vector_store.search(query_vector=v2, top_k=3)
    t1 = time.perf_counter()
    print(f"Search time: {(t1-t0)*1000:.2f} ms; chunks={len(chunks)}")

    await cache_service.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
