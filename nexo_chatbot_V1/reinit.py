import asyncio
from app.retrieval.vector_store import vector_store

async def main():
    await vector_store.connect()
    print("Collection recreated successfully!")
    await vector_store.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
