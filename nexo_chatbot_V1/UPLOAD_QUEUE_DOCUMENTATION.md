# File Upload Queue Documentation

## Overview

The file upload endpoint now supports **asynchronous processing with chunking and embedding through a Redis Queue**. This allows large files to be processed in the background without blocking the API endpoint.

## Features

### New Endpoints

#### 1. **POST /api/v1/upload-and-embed-queued**
Queues a file for asynchronous processing.

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: File upload

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size": 1024000,
  "status": "queued",
  "message": "File queued for processing. Use job_id '550e8400-e29b-41d4-a716-446655440000' to check status."
}
```

#### 2. **GET /api/v1/job-status/{job_id}**
Get the status of a queued upload job.

**Request:**
- Method: `GET`
- URL Parameter: `job_id` (the job ID returned from upload endpoint)

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "filename": "document.pdf",
  "file_size": 1024000,
  "chunks_created": 25,
  "chunks_indexed": 25,
  "is_finished": true,
  "is_failed": false,
  "is_queued": false,
  "is_started": false,
  "result": null,
  "error": null,
  "errors": []
}
```

**Status Values:**
- `queued` - File is waiting to be processed
- `started` - Processing has begun
- `completed` - Processing finished successfully
- `failed` - Processing failed (check `error` field)

## Architecture

### Components

1. **Queue Service** (`app/services/queue.py`)
   - Manages Redis Queue connections
   - Enqueues background jobs
   - Retrieves job status
   - Singleton pattern for connection management

2. **Upload Tasks** (`app/services/upload_tasks.py`)
   - Background task function `process_upload_chunks()`
   - Handles:
     - File text extraction (PDF, Word, Excel, PowerPoint, Text)
     - Text cleaning and normalization
     - Splitting into chunks
     - Embedding generation
     - Vector database indexing

3. **Upload Endpoint** (`app/api/routes/upload.py`)
   - New: `POST /upload-and-embed-queued` - Queue-based upload
   - New: `GET /job-status/{job_id}` - Check job status
   - Existing: `POST /upload` - Simple file upload
   - Existing: `POST /upload-and-embed` - Synchronous upload with embedding

4. **Worker** (`worker.py`)
   - Standalone worker process
   - Listens to Redis Queue
   - Processes background tasks

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

The `rq==1.16.0` package is already included in `requirements.txt`.

### 2. Ensure Redis is Running
```bash
redis-server
```

Or using Docker:
```bash
docker-compose up -d redis
```

### 3. Start the API Server
```bash
python -m uvicorn app.main:app --reload --port 8081
```

### 4. Start the Worker Process (in a separate terminal)
```bash
python worker.py
```

The worker will:
- Connect to Redis
- Listen for queued jobs
- Process files asynchronously
- Update job status in Redis

## Usage Example

### Python
```python
import requests
import time

# Upload file
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8081/api/v1/upload-and-embed-queued',
        files={'file': f}
    )

job_data = response.json()
job_id = job_data['job_id']
print(f"File queued with job_id: {job_id}")

# Poll job status
max_attempts = 60  # Try for up to 5 minutes
attempt = 0
while attempt < max_attempts:
    status_response = requests.get(
        f'http://localhost:8081/api/v1/job-status/{job_id}'
    )
    status_data = status_response.json()
    
    print(f"Status: {status_data['status']}")
    
    if status_data['status'] == 'completed':
        print(f"✓ Processing complete!")
        print(f"  - Chunks created: {status_data['chunks_created']}")
        print(f"  - Chunks indexed: {status_data['chunks_indexed']}")
        break
    elif status_data['status'] == 'failed':
        print(f"✗ Processing failed: {status_data['error']}")
        break
    
    time.sleep(5)  # Wait 5 seconds before polling again
    attempt += 1
```

### cURL
```bash
# Upload file
JOB_ID=$(curl -X POST \
  -F "file=@document.pdf" \
  http://localhost:8081/api/v1/upload-and-embed-queued | jq -r '.job_id')

echo "Job ID: $JOB_ID"

# Check status
curl http://localhost:8081/api/v1/job-status/$JOB_ID
```

## Processing Steps

When a file is uploaded via the `/upload-and-embed-queued` endpoint:

1. **File is queued** immediately with a job_id
2. **Worker picks up the task** when available
3. **Text Extraction**
   - Supports: PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), Text files
   - Extracts and preserves content structure
4. **Text Cleaning**
   - Removes boilerplate content
   - Normalizes whitespace
   - Handles encoding issues
5. **Chunking**
   - Splits text into manageable pieces (default: 512 tokens)
   - Maintains overlap for context (default: 75 tokens)
   - Keeps sentences intact when possible
6. **Embedding Generation**
   - Creates embeddings for each chunk using configured model
   - Batch processes for efficiency (50 chunks per batch)
   - Supported models:
     - `models/gemini-embedding-001` (Google - 3072 dimensions)
     - `all-MiniLM-L6-v2` (Local - 384 dimensions)
7. **Vector Indexing**
   - Stores embeddings and chunks in Qdrant vector database
   - Chunks become searchable for retrieval

## Comparison: Synchronous vs Queued

### Synchronous (`POST /upload-and-embed`)
- **Pros:**
  - Simple, immediate response
  - Good for small files
  - Direct error feedback
- **Cons:**
  - Blocks API request while processing
  - Large files may timeout
  - Poor user experience for large uploads

### Queued (`POST /upload-and-embed-queued`)
- **Pros:**
  - Immediate response with job_id
  - Handles large files efficiently
  - Non-blocking for API
  - Can scale with multiple workers
  - Better for production
- **Cons:**
  - Requires polling for status
  - Slightly more complex client code
  - Requires running worker process

## Configuration

### Settings in `app/config/settings.py`

```python
# Chunking
CHUNK_SIZE: int = 512           # Size of each chunk in tokens
CHUNK_OVERLAP: int = 75         # Overlap between chunks in tokens

# Embedding
EMBEDDING_MODEL: str = "models/gemini-embedding-001"
EMBEDDING_DIM: int = 3072       # Dimension of embeddings

# Redis Queue
REDIS_URL: str = "redis://localhost:6379"
```

### Batch Processing
```python
EMBED_BATCH_SIZE = 50  # Process 50 chunks at a time
```

## Monitoring

### View Job Statistics
```python
from app.services.queue import queue_service
from rq import Queue

queue_service.connect()
queue = queue_service.get_queue()

print(f"Queued jobs: {len(queue)}")
print(f"Failed jobs: {queue.failed_job_registry.count}")
print(f"Finished jobs: {queue.finished_job_registry.count}")
```

### Worker Logs
The worker will output logs like:
```
[INFO] [job-id-123] Starting upload processing: document.pdf, size: 1024000
[INFO] [job-id-123] Extracting text from document.pdf
[INFO] [job-id-123] Extracted 50000 characters of text
[INFO] [job-id-123] Cleaning text
[INFO] [job-id-123] Chunking text
[INFO] [job-id-123] Created 25 chunks from file
[INFO] [job-id-123] Processing 25 chunks for embedding and indexing
[INFO] [job-id-123] Processing batch 1/1
[INFO] [job-id-123] Indexed batch 1: 25 chunks
[INFO] [job-id-123] Successfully indexed 25 chunks from file
[INFO] [job-id-123] Upload processing completed successfully
```

## Error Handling

### Common Issues

**Issue:** Worker not processing jobs
- **Solution:** Ensure worker process is running (`python worker.py`)

**Issue:** "Unsupported file format"
- **Solution:** Check supported formats (PDF, .docx, .xlsx, .pptx, .txt)

**Issue:** Job status returns "failed"
- **Solution:** Check the `error` field in the response for details

**Issue:** Long processing time
- **Solution:** 
  - Larger files naturally take longer
  - Check Redis/Vector DB performance
  - Scale with multiple worker processes

## Production Deployment

### Using Systemd Service
```ini
[Unit]
Description=Nexo Chatbot Upload Queue Worker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/app
ExecStart=/usr/bin/python3 worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start with:
```bash
sudo systemctl start nexo-worker
```

### Using Supervisor
```ini
[program:nexo-worker]
command=/path/to/venv/bin/python worker.py
directory=/path/to/app
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/nexo-worker.log
```

### Health Monitoring
Include worker status in health checks:
```python
@app.get("/v1/health")
async def health():
    # ... existing checks ...
    
    # Check worker
    queue = queue_service.get_queue()
    worker_count = len(queue.workers)
    
    return HealthResponse(
        status="healthy" if worker_count > 0 else "degraded",
        components={
            # ... existing components ...
            "queue_worker": "ok" if worker_count > 0 else "no_workers"
        }
    )
```

## Next Steps

1. **Multiple Workers:** Run multiple worker processes for parallel processing
   ```bash
   python worker.py --name worker1 &
   python worker.py --name worker2 &
   ```

2. **Custom Chunk Sizes:** Adjust `CHUNK_SIZE` and `CHUNK_OVERLAP` per file type

3. **Webhook Notifications:** Add webhooks to notify when processing completes

4. **Progress Tracking:** Stream progress updates via WebSocket instead of polling

5. **Priority Queue:** Implement priority levels for urgent uploads
