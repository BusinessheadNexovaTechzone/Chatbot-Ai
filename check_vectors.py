import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config.settings import get_settings
from qdrant_client import AsyncQdrantClient

async def check_vector_store():
    settings = get_settings()

    try:
        if settings.QDRANT_URL:
            client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )
        elif settings.QDRANT_HOST.startswith(("http://", "https://")):
            client = AsyncQdrantClient(
                url=settings.QDRANT_HOST,
                api_key=settings.QDRANT_API_KEY,
            )
        else:
            client = AsyncQdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY,
            )

        # Get collection info
        collection_info = await client.get_collection(settings.QDRANT_COLLECTION)
        print(f"Collection: {settings.QDRANT_COLLECTION}")
        print(f"Total vectors: {collection_info.points_count}")
        print(f"Vector dimension: {collection_info.config.vectors.size}")

        if collection_info.points_count > 0:
            # Get some sample points
            scroll_result = await client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                limit=3
            )

            print("\nSample vectors:")
            for i, point in enumerate(scroll_result[0]):
                print(f"\nVector {i+1}:")
                print(f"  ID: {point.id}")
                print(f"  Source: {point.payload.get('source', 'unknown')}")
                print(f"  Content preview: {point.payload.get('content', '')[:200]}...")

        await client.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_vector_store())