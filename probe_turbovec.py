import asyncio
import time
from app.retrieval.embeddings import embedding_service
from app.retrieval.vector_store import vector_store

async def probe():
    await vector_store.connect()
    # measure embedding
    q = "who is the ceo?"
    t0 = time.perf_counter()
    vec = await embedding_service.embed_query(q)
    t1 = time.perf_counter()
    print(f"Embedding time: {(t1-t0)*1000:.2f} ms; vector length: {len(vec)}")
    # measure turbo search
    t0 = time.perf_counter()
    chunks = await vector_store.search(query_vector=vec, top_k=3)
    t1 = time.perf_counter()
    print(f"TurboVec search time: {(t1-t0)*1000:.2f} ms; returned {len(chunks)} chunks")

if __name__ == '__main__':
    asyncio.run(probe())
