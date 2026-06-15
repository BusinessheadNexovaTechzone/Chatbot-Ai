import requests

url = "http://127.0.0.1:8081/api/v1/chat"
data = {
    "query": "Our Products",
    "session_id": "string",
    "stream": False,
    "assistant_name": "Assistant"
}

try:
    response = requests.post(url, json=data, timeout=30)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Answer: {result.get('answer', '')}")
        print(f"Intent: {result.get('intent', '')}")
        print(f"Confidence: {result.get('confidence', 0)}")
        print(f"Sources: {len(result.get('sources', []))}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")