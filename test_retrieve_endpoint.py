#!/usr/bin/env python3
"""
Test script for the data retrieval endpoints.
This demonstrates how to query for relevant data chunks from uploaded files.
Tests both /api/v1/chat/retrieve and /api/v1/upload/retrieve endpoints.
"""

import requests
import json

def test_retrieve_chat():
    """Test the /api/v1/chat/retrieve endpoint"""
    return _test_retrieve_endpoint("http://localhost:8081/api/v1/chat/retrieve", "Chat Retrieve")

def test_retrieve_upload():
    """Test the /api/v1/upload/retrieve endpoint"""
    return _test_retrieve_endpoint("http://localhost:8081/api/v1/upload/retrieve", "Upload Retrieve")

def _test_retrieve_endpoint(url, endpoint_name):
    """Test a retrieve endpoint"""

    # Query to search for
    query = "What is the main topic of the uploaded documents?"

    try:
        payload = {"query": query}
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            result = response.json()
            print(f"✅ {endpoint_name} successful!")
            print(f"⏱️  Latency: {result['latency_ms']:.2f}ms")
            print(f"📄 Chunks found: {len(result['chunks'])}")

            if result['chunks']:
                print(f"\n📋 Retrieved chunks from {endpoint_name}:")
                for i, chunk in enumerate(result['chunks'][:3], 1):  # Show first 3 chunks
                    print(f"\n--- Chunk {i} ---")
                    print(f"Source: {chunk['source']}")
                    print(f"Score: {chunk['score']:.3f}")
                    print(f"Content preview: {chunk['content'][:200]}...")
                return True
            else:
                print("📭 No relevant chunks found for this query")
                return True
        else:
            print(f"❌ {endpoint_name} failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to server for {endpoint_name}. Make sure the FastAPI app is running on port 8081.")
        return False
    except Exception as e:
        print(f"❌ {endpoint_name} test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing data retrieval endpoints...")
    print("=" * 50)

    chat_success = test_retrieve_chat()
    print("\n" + "=" * 50)
    upload_success = test_retrieve_upload()

    print("\n" + "=" * 50)
    if chat_success and upload_success:
        print("✅ All retrieve endpoints working!")
    elif chat_success:
        print("⚠️  Chat retrieve working, upload retrieve failed")
    elif upload_success:
        print("⚠️  Upload retrieve working, chat retrieve failed")
    else:
        print("❌ Both retrieve endpoints failed")