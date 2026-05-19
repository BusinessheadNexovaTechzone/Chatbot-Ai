import requests

url = "http://127.0.0.1:8081/api/v1/retrieve"
query = "company name"

try:
    response = requests.post(url, json={"query": query}, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Chunks: {len(data.get('chunks', []))}")
        for chunk in data.get('chunks', [])[:1]:
            print(f"Content: {chunk.get('content', '')[:300]}...")
except Exception as e:
    print(f"Exception: {e}")