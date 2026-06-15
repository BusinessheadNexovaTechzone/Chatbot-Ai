import requests

urls = [
    'http://127.0.0.1:8000/openapi.json',
    'http://127.0.0.1:8000/docs',
    'http://127.0.0.1:8000/api/v1/retrieve',
]

for url in urls:
    try:
        if url.endswith('/api/v1/retrieve'):
            r = requests.post(url, json={'query': 'hello'})
        else:
            r = requests.get(url)
        print(url, r.status_code)
        print(r.text[:400])
    except Exception as e:
        print(url, 'ERROR', e)
