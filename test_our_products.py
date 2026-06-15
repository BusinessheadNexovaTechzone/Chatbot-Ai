import requests

url = "http://127.0.0.1:8081/api/v1/retrieve"
query = "Our Products"

try:
    response = requests.post(url, json={"query": query}, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Chunks: {len(data.get('chunks', []))}")
        print(f"Latency: {data.get('latency_ms', 0)}ms")
        for i, chunk in enumerate(data.get('chunks', [])[:3]):
            print(f"Chunk {i+1}:")
            print(f"Content: {chunk.get('content', '')}")
            print(f"Score: {chunk.get('score', 0)}")
            print("---")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")