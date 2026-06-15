import requests
import json

# Test the retrieve endpoint
url = "http://127.0.0.1:8081/api/v1/retrieve"
query = "What is the main topic of the uploaded documents?"

try:
    response = requests.post(url, json={"query": query})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

    if response.status_code == 200:
        data = response.json()
        print(f"Chunks found: {len(data.get('chunks', []))}")
        print(f"Latency: {data.get('latency_ms', 0)}ms")

        for i, chunk in enumerate(data.get('chunks', [])[:3]):
            print(f"\nChunk {i+1}:")
            print(f"  Content: {chunk.get('content', '')[:200]}...")
            print(f"  Source: {chunk.get('source', '')}")
            print(f"  Score: {chunk.get('score', 0)}")

except Exception as e:
    print(f"Error: {e}")