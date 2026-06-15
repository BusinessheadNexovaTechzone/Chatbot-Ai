import asyncio
import json
import httpx

async def test_hindi():
    async with httpx.AsyncClient() as client:
        payload = {
            "query": "गूगल के CEO कौन हैं?",
            "session_id": "string",
            "stream": False,
            "assistant_name": "Assistant",
            "use_uploaded_docs": False,
            "global_search": True
        }
        
        print("Testing Hindi query...")
        print(f"Query: {payload['query']}")
        print()
        
        try:
            response = await client.post(
                "http://localhost:8081/api/v1/chat",
                json=payload,
                timeout=30.0
            )
            print(f"Status: {response.status_code}")
            print(f"Response:\n{json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_hindi())
