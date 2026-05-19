import requests

# Test retrieve endpoint
url = "http://127.0.0.1:8081/api/v1/retrieve"
query = "What is PDF text extraction?"

try:
    response = requests.post(url, json={"query": query}, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Chunks: {len(data.get('chunks', []))}")
        print(f"Latency: {data.get('latency_ms', 0)}ms")
        for chunk in data.get('chunks', [])[:2]:
            print(f"Content: {chunk.get('content', '')[:100]}...")
            print(f"Score: {chunk.get('score', 0)}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")