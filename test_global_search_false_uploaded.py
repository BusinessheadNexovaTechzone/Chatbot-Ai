import asyncio
import json
import httpx

async def test_endpoint():
    async with httpx.AsyncClient() as client:
        payload = {
            "query": "what is python",
            "session_id": "string",
            "stream": False,
            "assistant_name": "Assistant",
            "use_uploaded_docs": True,
            "global_search": False
        }
        
        print("Testing endpoint with payload (global_search=false, use_uploaded_docs=true):")
        print(json.dumps(payload, indent=2))
        print("\n" + "="*50 + "\n")
        
        try:
            response = await client.post(
                "http://localhost:8081/api/v1/chat",
                json=payload,
                timeout=30.0
            )
            print(f"Status: {response.status_code}")
            print(f"Response:\n{json.dumps(response.json(), indent=2)}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_endpoint())
