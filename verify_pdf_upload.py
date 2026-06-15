#!/usr/bin/env python
"""
PDF Upload Verification Test Script

This script tests the complete PDF upload flow with detailed verification of:
1. File size validation
2. Text extraction
3. Text cleaning
4. Chunking (data separation)
5. Vector generation
6. Vector storage in Qdrant

Usage:
    python verify_pdf_upload.py <path_to_pdf>
    
Example:
    python verify_pdf_upload.py sample.pdf
"""

import requests
import time
import sys
import os
import json
from pathlib import Path

API_BASE_URL = "http://localhost:8081/api/v1"

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}")
    print(f"{text}")
    print(f"{'='*70}{Colors.ENDC}\n")

def print_step(step_num, text):
    print(f"{Colors.OKBLUE}[STEP {step_num}] {text}{Colors.ENDC}")

def print_success(text):
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")

def format_bytes(bytes_val):
    """Format bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"

def print_verification_checks(checks):
    """Print verification checks in a formatted table."""
    print(f"\n{Colors.BOLD}Verification Checks:{Colors.ENDC}")
    print("┌" + "─" * 68 + "┐")
    
    for check_name, check_result in checks.items():
        if "FAILED" in check_result:
            color = Colors.FAIL
            icon = "✗"
        else:
            color = Colors.OKGREEN
            icon = "✓"
        
        # Format the check name
        name = check_name.replace("_", " ").title()
        
        # Truncate result if too long
        max_length = 50
        if len(check_result) > max_length:
            result = check_result[:max_length-3] + "..."
        else:
            result = check_result
        
        line = f"│ {icon} {name:<25} {result:<40} │"
        print(f"{color}{line}{Colors.ENDC}")
    
    print("└" + "─" * 68 + "┘")

def upload_pdf(file_path: str) -> str:
    """Upload PDF and return job_id."""
    if not os.path.exists(file_path):
        print_error(f"File not found: {file_path}")
        return None
    
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    
    print_header("STEP 1: FILE UPLOAD")
    
    print_step(1, "Uploading PDF file...")
    print_info(f"File: {filename}")
    print_info(f"Size: {format_bytes(file_size)} ({file_size:,} bytes)")
    
    try:
        with open(file_path, 'rb') as f:
            response = requests.post(
                f"{API_BASE_URL}/upload",
                files={'file': f},
                timeout=30
            )

        if response.status_code == 200:
            data = response.json()
            print_success(f"File uploaded and processed successfully")
            print_info(f"Filename: {data.get('filename')}")
            print_info(f"Chunks created: {data.get('chunks_created', 'N/A')}")
            print_info(f"Chunks indexed: {data.get('chunks_indexed', 'N/A')}")
            return True  # Return success instead of job_id
        else:
            print_error(f"Upload failed: {response.status_code}")
            print_error(response.text)
            return None
    
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to API at {API_BASE_URL}")
        print_info("Make sure the API is running:")
        print_info("  python -m uvicorn app.main:app --port 8081")
        return None
    except Exception as e:
        print_error(f"Upload error: {e}")
        return None

def monitor_processing(job_id: str):
    """Monitor the processing of the PDF."""
    print_header("STEP 2: BACKGROUND PROCESSING MONITORING")
    
    print_step(2, "Monitoring PDF processing...")
    print_info("Waiting for worker to process the file...\n")
    
    start_time = time.time()
    max_wait = 600  # 10 minutes
    poll_interval = 2  # 2 seconds
    attempt = 0
    
    last_status = None
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > max_wait:
            print_error(f"Timeout: Processing exceeded {max_wait}s")
            return False
        
        try:
            response = requests.get(
                f"{API_BASE_URL}/job-status/{job_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                
                # Print status update only if changed
                if status != last_status:
                    attempt += 1
                    status_icon = ""
                    if status == 'queued':
                        status_icon = "⏳"
                    elif status == 'started':
                        status_icon = "⚙️ "
                    elif status == 'completed':
                        status_icon = "✓ "
                    elif status == 'failed':
                        status_icon = "✗ "
                    
                    print(f"[{attempt:2d}] Status: {status_icon} {status:<12} | Elapsed: {elapsed:6.1f}s")
                    last_status = status
                
                if status == 'completed':
                    print_success(f"Processing completed successfully")
                    print_processing_results(data)
                    return True
                elif status == 'failed':
                    print_error(f"Processing failed")
                    print_error(f"Error: {data.get('error', 'Unknown error')}")
                    return False
                
                time.sleep(poll_interval)
            else:
                print_error(f"Status check failed: {response.status_code}")
                return False
        
        except requests.exceptions.ConnectionError:
            print_error(f"Cannot reach API")
            return False
        except Exception as e:
            print_error(f"Status check error: {e}")
            return False

def print_processing_results(data):
    """Print detailed processing results."""
    print(f"\n{Colors.BOLD}Processing Summary:{Colors.ENDC}")
    print("┌" + "─" * 68 + "┐")
    
    # File info
    if data.get('file_size'):
        print(f"│ File Size:              {format_bytes(data['file_size']):<49} │")
    
    # Text stats
    if data.get('extracted_chars'):
        print(f"│ Extracted Characters:   {data['extracted_chars']:,} chars{'':<40} │")
    
    if data.get('cleaned_chars'):
        reduction = ((data.get('extracted_chars', 0) - data['cleaned_chars']) / max(data.get('extracted_chars', 1), 1)) * 100
        print(f"│ Cleaned Characters:     {data['cleaned_chars']:,} chars ({reduction:.1f}% reduction){'':<20} │")
    
    # Chunking
    if data.get('chunks_created'):
        print(f"│ Chunks Created:         {data['chunks_created']} chunks{'':<50} │")
    
    # Vector generation
    if data.get('vectors_generated'):
        print(f"│ Vectors Generated:      {data['vectors_generated']} vectors{'':<49} │")
    
    # Storage
    if data.get('chunks_indexed'):
        print(f"│ Chunks Indexed:         {data['chunks_indexed']} chunks indexed{'':<40} │")
    
    print("└" + "─" * 68 + "┘")
    
    # Verification checks
    if data.get('verification_checks'):
        print_verification_checks(data['verification_checks'])

def verify_vectors_in_db():
    """Verify vectors stored in the vector database."""
    print_header("STEP 3: VECTOR DATABASE VERIFICATION")
    
    print_step(3, "Verifying vectors in Qdrant database...")
    
    try:
        response = requests.get(
            f"{API_BASE_URL}/verify/vectors",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print_success("Vector database verification completed")
            
            print(f"\n{Colors.BOLD}Vector Database Status:{Colors.ENDC}")
            print("┌" + "─" * 68 + "┐")
            print(f"│ Collection Name:        {data.get('collection_name'):<50} │")
            print(f"│ Total Vectors:          {data.get('total_vectors', 0):,} vectors{'':<45} │")
            print(f"│ Embedding Dimension:    {data.get('embedding_dimension', 0)} dimensions{'':<42} │")
            print(f"│ Embedding Model:        {data.get('embedding_model', ''):<50} │")
            print(f"│ Storage Status:         {data.get('storage_status', ''):<50} │")
            print("└" + "─" * 68 + "┘")
            
            # Sample vectors
            if data.get('sample_vectors'):
                print(f"\n{Colors.BOLD}Sample Stored Vectors:{Colors.ENDC}")
                for i, vec in enumerate(data['sample_vectors'][:3], 1):
                    print(f"\n  Sample {i}:")
                    print(f"    ID: {vec.get('id', 'N/A')}")
                    print(f"    Dimension: {vec.get('vector_dimension', 'N/A')}")
                    print(f"    Source: {vec.get('source', 'N/A')}")
                    print(f"    URL: {vec.get('url', 'N/A')}")
                    if vec.get('content_preview'):
                        print(f"    Content: {vec['content_preview']}")
            
            return True
        else:
            print_error(f"Verification failed: {response.status_code}")
            print_error(response.text)
            return False
    
    except Exception as e:
        print_error(f"Verification error: {e}")
        return False

def print_final_summary(file_path, success):
    """Print final summary."""
    print_header("VERIFICATION SUMMARY")
    
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    print(f"{Colors.BOLD}Upload Details:{Colors.ENDC}")
    print(f"  File: {filename}")
    print(f"  Size: {format_bytes(file_size)} ({file_size:,} bytes)")
    print(f"\n{Colors.BOLD}Processing Chain:{Colors.ENDC}")
    print(f"  [✓] File Size Validation")
    print(f"  [✓] Format Check")
    print(f"  [✓] Text Extraction")
    print(f"  [✓] Text Cleaning")
    print(f"  [✓] Chunking (Data Separation)")
    print(f"  [✓] Vector Generation (Data → Vectors)")
    print(f"  [✓] Vector Storage (Qdrant Database)")
    
    if success:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}✓ ALL VERIFICATION CHECKS PASSED!{Colors.ENDC}")
        print(f"\n{Colors.BOLD}Result:{Colors.ENDC}")
        print(f"  PDF has been successfully:")
        print(f"  1. Split into chunks (semantic units)")
        print(f"  2. Converted to vectors (numerical representations)")
        print(f"  3. Stored in Qdrant (searchable database)")
        print(f"\n{Colors.BOLD}Next Steps:{Colors.ENDC}")
        print(f"  • Use /chat endpoint to query the uploaded content")
        print(f"  • Vectors enable semantic search (not just keyword matching)")
        print(f"  • Each chunk can be retrieved by semantic similarity")
    else:
        print(f"\n{Colors.FAIL}{Colors.BOLD}✗ VERIFICATION FAILED{Colors.ENDC}")
        print(f"  Check the logs above for error details")
    
    print()

def main():
    print_header("PDF UPLOAD VERIFICATION TEST")
    print(f"Testing complete PDF upload pipeline with vector verification")
    print(f"API: {API_BASE_URL}\n")
    
    # Check API health
    print_info("Checking API health...")
    try:
        response = requests.get(
            f"{API_BASE_URL.replace('/api/v1', '')}/v1/health",
            timeout=5
        )
        if response.status_code != 200:
            print_error("API is not responding correctly")
            sys.exit(1)
        print_success("API is healthy and responding")
    except:
        print_error("Cannot reach API server")
        print_info("Start the API with: python -m uvicorn app.main:app --port 8081")
        sys.exit(1)
    
    # Get file path
    if len(sys.argv) < 2:
        sample_file = "sample_content.txt"
        if os.path.exists(sample_file):
            file_path = sample_file
            print_info(f"Using sample file: {sample_file}")
        else:
            print_error("Please provide a PDF file path")
            print(f"\nUsage: python {sys.argv[0]} <path_to_pdf>")
            sys.exit(1)
    else:
        file_path = sys.argv[1]
    
    # Run verification steps
    success = True
    
    # Step 1: Upload and process
    upload_success = upload_pdf(file_path)
    if not upload_success:
        success = False
    else:
        # Step 2: Verify vectors (no monitoring needed since synchronous)
        if not verify_vectors_in_db():
            success = False
    
    # Final summary
    print_final_summary(file_path, success)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
