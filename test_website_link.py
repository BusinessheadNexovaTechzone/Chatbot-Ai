import asyncio
import httpx

async def test_website_link():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8081/api/v1/chat",
            json={
                "query": "website link",
                "session_id": "test_session",
                "stream": False,
                "assistant_name": "Assistant"
            },
            timeout=30
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")

if __name__ == "__main__":
    asyncio.run(test_website_link())