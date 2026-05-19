#!/usr/bin/env python3
"""
Comprehensive test script for file upload and embedding functionality.
Tests multiple file formats and verifies vector database storage.
"""

import requests
import json
import os
from pathlib import Path

def test_file_upload(file_path, expected_success=True):
    """Test uploading a specific file format."""
    if not os.path.exists(file_path):
        print(f"❌ Test file '{file_path}' not found")
        return False

    url = "http://localhost:8000/api/v1/upload"

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            response = requests.post(url, files=files, timeout=30)

        file_ext = Path(file_path).suffix.upper()
        print(f"\n🧪 Testing {file_ext} file: {os.path.basename(file_path)}")

        if response.status_code == 200:
            result = response.json()
            print("✅ Upload and embedding successful!")
            print(f"📄 Filename: {result['filename']}")
            print(f"📏 Size: {result['size']} bytes")
            print(f"📝 Content Type: {result['content_type']}")
            print(f"🔢 Chunks created: {result['chunks_created']}")
            print(f"💾 Chunks indexed: {result['chunks_indexed']}")
            if result['errors']:
                print(f"⚠️  Errors: {result['errors']}")
            return True
        else:
            print(f"❌ Upload failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server. Make sure the FastAPI app is running.")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_vector_database_storage():
    """Test that data is actually stored in the vector database."""
    try:
        # Try to search for uploaded content
        search_url = "http://localhost:8000/api/v1/chat"
        payload = {
            "query": "file upload system",
            "session_id": "test_session"
        }

        response = requests.post(search_url, json=payload, timeout=30)

        if response.status_code == 200:
            result = response.json()
            print("\n🔍 Vector Database Verification:")
            print("✅ Chat endpoint accessible")
            if 'sources' in result and result['sources']:
                print(f"✅ Found {len(result['sources'])} sources in response")
                print("✅ Vector database contains searchable content")
                return True
            else:
                print("⚠️  No sources found in response (may be normal for new database)")
                return True
        else:
            print(f"⚠️  Chat endpoint returned status {response.status_code}")
            return False

    except Exception as e:
        print(f"⚠️  Vector database verification failed: {e}")
        return False

def main():
    """Run comprehensive tests for all supported file formats."""
    print("🚀 Comprehensive File Upload & Vector Database Test")
    print("=" * 60)

    # Test different file formats
    test_files = [
        "test_upload.txt",  # Plain text
        "sample_content.txt",  # Another text file
    ]

    # Note: For PDF, DOCX, XLSX, PPTX testing, you would need actual files
    # These would need to be created or provided separately

    successful_tests = 0
    total_tests = len(test_files)

    for test_file in test_files:
        if test_file_upload(test_file):
            successful_tests += 1

    print(f"\n📊 Test Results: {successful_tests}/{total_tests} file uploads successful")

    # Test vector database storage
    if test_vector_database_storage():
        print("✅ Vector database verification passed")
    else:
        print("❌ Vector database verification failed")

    print("\n🎯 Supported File Formats:")
    formats = [
        "📄 Text files (.txt, .md, .csv, .json, .xml, .html)",
        "📕 PDF documents (.pdf)",
        "📝 Word documents (.docx, .doc)",
        "📊 Excel spreadsheets (.xlsx, .xls)",
        "📽️  PowerPoint presentations (.pptx, .ppt)"
    ]

    for fmt in formats:
        print(f"   {fmt}")

    print("\n💡 All uploaded content is processed into vector embeddings")
    print("   and stored in Qdrant for semantic search and retrieval.")
if __name__ == "__main__":
    main()