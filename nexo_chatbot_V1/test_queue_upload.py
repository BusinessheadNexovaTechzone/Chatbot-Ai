#!/usr/bin/env python
"""
Test script for the queued file upload endpoint.

This script tests the asynchronous file upload with chunking and embedding.

Usage:
    python test_queue_upload.py <path_to_file>
    
Example:
    python test_queue_upload.py sample_content.txt
"""

import requests
import time
import sys
import os
from pathlib import Path

API_BASE_URL = "http://localhost:8081/api/v1"
POLL_INTERVAL = 2  # seconds
MAX_WAIT_TIME = 600  # 10 minutes

def upload_file(file_path: str) -> str:
    """Upload file and return job_id."""
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return None
    
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    
    print(f"\n📤 Uploading: {filename} ({file_size:,} bytes)")
    
    try:
        with open(file_path, 'rb') as f:
            response = requests.post(
                f"{API_BASE_URL}/upload",
                files={'file': f},
                timeout=30
            )

        if response.status_code == 200:
            data = response.json()
            print(f"✅ File uploaded and processed successfully!")
            print(f"   Filename: {data.get('filename')}")
            print(f"   Chunks created: {data.get('chunks_created', 'N/A')}")
            print(f"   Chunks indexed: {data.get('chunks_indexed', 'N/A')}")
            return True
        else:
            print(f"❌ Upload failed: {response.status_code}")
            print(f"   {response.text}")
            return None
    
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {API_BASE_URL}")
        print(f"   Make sure the API server is running: python -m uvicorn app.main:app --port 8081")
        return None
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return None

def poll_job_status(job_id: str):
    """Poll job status until completion."""
    print(f"\n⏳ Monitoring job: {job_id}\n")
    
    start_time = time.time()
    attempt = 0
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > MAX_WAIT_TIME:
            print(f"\n❌ Timeout: Job processing exceeded {MAX_WAIT_TIME}s")
            return False
        
        try:
            response = requests.get(
                f"{API_BASE_URL}/job-status/{job_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                
                # Print status update
                attempt += 1
                print(f"[{attempt:2d}] Status: {status:<12} | Elapsed: {elapsed:6.1f}s", end="")
                
                if status == 'queued':
                    print(" (waiting in queue...)")
                elif status == 'started':
                    print(" (processing...)")
                elif status == 'completed':
                    print(" ✅")
                    print_completion_details(data)
                    return True
                elif status == 'failed':
                    print(" ❌")
                    print_error_details(data)
                    return False
                else:
                    print()
                
                time.sleep(POLL_INTERVAL)
            else:
                print(f"\n❌ Status check failed: {response.status_code}")
                return False
        
        except requests.exceptions.ConnectionError:
            print(f"\n❌ Cannot reach API - is the server still running?")
            return False
        except Exception as e:
            print(f"\n❌ Status check error: {e}")
            return False

def print_completion_details(data):
    """Print job completion details."""
    print("\n" + "="*60)
    print("✅ JOB COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"Job ID:           {data.get('job_id')}")
    print(f"Filename:         {data.get('filename')}")
    print(f"File Size:        {data.get('file_size', 'N/A'):,} bytes")
    print(f"Chunks Created:   {data.get('chunks_created', 0)}")
    print(f"Chunks Indexed:   {data.get('chunks_indexed', 0)}")
    
    if data.get('errors'):
        print(f"\n⚠️  Errors/Warnings:")
        for error in data['errors']:
            print(f"   - {error}")
    else:
        print(f"\n✓ No errors")
    
    print("="*60 + "\n")

def print_error_details(data):
    """Print job error details."""
    print("\n" + "="*60)
    print("❌ JOB FAILED!")
    print("="*60)
    print(f"Job ID:    {data.get('job_id')}")
    print(f"Filename:  {data.get('filename', 'N/A')}")
    
    if data.get('error'):
        print(f"\nError: {data.get('error')}")
    
    if data.get('errors'):
        print(f"\nDetails:")
        for error in data['errors']:
            print(f"  - {error}")
    
    print("="*60 + "\n")

def check_api_health():
    """Check if API is running."""
    try:
        response = requests.get(
            f"{API_BASE_URL.replace('/api/v1', '')}/v1/health",
            timeout=5
        )
        if response.status_code == 200:
            return True, response.json()
        else:
            return False, None
    except:
        return False, None

def main():
    print("\n" + "="*60)
    print("NEXO CHATBOT - QUEUE UPLOAD TEST")
    print("="*60)
    
    # Check API health
    print("\n🔍 Checking API health...")
    is_healthy, health_data = check_api_health()
    
    if not is_healthy:
        print("❌ API is not responding!")
        print(f"   Make sure the API is running:")
        print(f"   python -m uvicorn app.main:app --port 8081")
        sys.exit(1)
    
    print("✅ API is running")
    
    # Get file path from arguments
    if len(sys.argv) < 2:
        # Use sample file if available
        sample_file = "sample_content.txt"
        if os.path.exists(sample_file):
            file_path = sample_file
            print(f"\n📝 Using sample file: {sample_file}")
        else:
            print("\n❌ Please provide a file to upload")
            print(f"\nUsage: python {sys.argv[0]} <path_to_file>")
            print(f"\nSupported formats:")
            print(f"  - PDF (.pdf)")
            print(f"  - Word (.docx)")
            print(f"  - Excel (.xlsx)")
            print(f"  - PowerPoint (.pptx)")
            print(f"  - Text (.txt, .csv, etc.)")
            sys.exit(1)
    else:
        file_path = sys.argv[1]
    
    # Upload file
    success = upload_file(file_path)
    if not success:
        sys.exit(1)
    
    # No monitoring needed - synchronous processing
    print("✨ Test completed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    main()
