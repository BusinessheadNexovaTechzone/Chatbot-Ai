#!/usr/bin/env python3
"""
Test script for the file upload endpoint.
This demonstrates how to upload a file and have it processed into vector embeddings.
"""

import requests
import json

def test_upload():
    """Test the /api/v1/upload endpoint"""

    # File to upload
    file_path = "test_upload.txt"

    # API endpoint
    url = "http://localhost:8000/api/v1/upload"

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_path, f, 'text/plain')}
            response = requests.post(url, files=files)

        if response.status_code == 200:
            result = response.json()
            print("✅ Upload successful!")
            print(f"📄 Filename: {result['filename']}")
            print(f"📏 Size: {result['size']} bytes")
            print(f"📝 Is text: {result['is_text']}")
            if 'chunks_created' in result and result['chunks_created'] is not None:
                print(f"🔢 Chunks created: {result['chunks_created']}")
                print(f"💾 Chunks indexed: {result['chunks_indexed']}")
                print("✅ File was processed and embedded")
            else:
                print("📄 File content returned (unsupported format or raw content)")
            if result.get('errors'):
                print(f"⚠️  Errors: {result['errors']}")
        else:
            print(f"❌ Upload failed with status {response.status_code}")
            print(f"Response: {response.text}")

    except FileNotFoundError:
        print(f"❌ Test file '{file_path}' not found")
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server. Make sure the FastAPI app is running.")
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    print("Testing file upload endpoint...")
    test_upload()