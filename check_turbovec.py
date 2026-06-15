import numpy as np
from app.retrieval.vector_store import TurboVecBackend


def main():
    backend = TurboVecBackend()
    backend.clear()
    backend.connect()

    dim = backend._dim
    vectors = [np.random.rand(dim).astype(np.float32).tolist() for _ in range(5)]
    chunks = [
        {
            "content": f"TurboVec test document {i}",
            "source": "check_turbovec",
            "url": "",
            "section": "test",
            "timestamp": "",
        }
        for i in range(len(vectors))
    ]

    backend.add_vectors(chunks, vectors)
    query_vector = vectors[2]

    results = backend.search(query_vector, k=3)
    print("First search results:")
    for item in results:
        print(f"  id={item.id}, score={item.score:.4f}, content={item.content}")

    if not results:
        raise SystemExit("TurboVec search returned no results")

    backend2 = TurboVecBackend()
    backend2.connect()
    loaded_results = backend2.search(query_vector, k=3)
    print("Loaded index search results:")
    for item in loaded_results:
        print(f"  id={item.id}, score={item.score:.4f}, content={item.content}")

    if not loaded_results:
        raise SystemExit("Reloaded TurboVec index search returned no results")

    backend.clear()
    print("TurboVec add/search/load test completed successfully.")


if __name__ == "__main__":
    main()
