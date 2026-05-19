#!/usr/bin/env python3
"""Clear all vectors from Qdrant collection to start fresh."""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config.settings import get_settings
from qdrant_client import AsyncQdrantClient

async def clear_collection():
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
        
        # Delete the entire collection
        await client.delete_collection(settings.QDRANT_COLLECTION)
        print(f"✅ Deleted collection: {settings.QDRANT_COLLECTION}")
        
        # Recreate it
        from qdrant_client.models import Distance, VectorParams
        await client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        print(f"✅ Recreated collection: {settings.QDRANT_COLLECTION}")
        
        await client.close()
        print("\n🔄 Ready to re-upload documents with new chunking strategy")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(clear_collection())
