import requests

# Upload the sample content
url = "http://127.0.0.1:8081/api/v1/upload"

try:
    with open("sample_content.txt", "rb") as f:
        files = {"file": ("sample_content.txt", f, "text/plain")}
        response = requests.post(url, files=files)

    print(f"Upload status: {response.status_code}")
    print(f"Response: {response.text}")

except Exception as e:
    print(f"Error: {e}")