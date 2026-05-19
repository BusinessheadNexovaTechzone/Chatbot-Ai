# File Upload Queue Implementation - Quick Start

## ✅ What's Been Implemented

Your file upload endpoint now supports **asynchronous chunking and embedding with queue-based processing**.

## 📋 New Files Created

### 1. **app/services/queue.py**
- Redis Queue service for managing background jobs
- Enqueue jobs, retrieve status, singleton connection management

### 2. **app/services/upload_tasks.py**
- Background task function: `process_upload_chunks()`
- Handles: Extract → Clean → Chunk → Embed → Index

### 3. **worker.py**
- Standalone worker process to handle queued tasks
- Listens to Redis Queue and processes jobs

### 4. **UPLOAD_QUEUE_DOCUMENTATION.md**
- Complete documentation with examples and guides

## 🔄 Modified Files

| File | Changes |
|------|---------|
| `requirements.txt` | Added `rq==1.16.0` |
| `app/api/routes/upload.py` | Added 2 new endpoints |
| `app/models/schemas.py` | Added 2 new response schemas |
| `app/main.py` | Initialized queue service on startup |

## 🚀 New API Endpoints

### Upload file for queued processing
```bash
POST /api/v1/upload-and-embed-queued
```
**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "document.pdf",
  "status": "queued",
  "message": "File queued for processing..."
}
```

### Check job status
```bash
GET /api/v1/job-status/{job_id}
```
**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "chunks_created": 25,
  "chunks_indexed": 25
}
```

## 🛠️ Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Ensure Redis is Running
```bash
redis-server
# OR with Docker
docker-compose up -d redis
```

### 3. Start API Server
```bash
python -m uvicorn app.main:app --reload --port 8081
```

### 4. Start Worker (separate terminal)
```bash
python worker.py
```

## 📊 Processing Flow

```
User Upload
    ↓
POST /upload-and-embed-queued
    ↓
Returns job_id immediately ← ✓ Non-blocking!
    ↓
Worker picks up job
    ↓
Extract text from file
    ↓
Clean and normalize text
    ↓
Split into chunks (batches)
    ↓
Generate embeddings (batch processing)
    ↓
Index in vector database
    ↓
Job marked: COMPLETED
    ↓
Client polls GET /job-status/{job_id}
    ↓
Gets chunks_created & chunks_indexed
```

## 💡 Key Benefits

✓ **Non-blocking** - API responds immediately  
✓ **Scalable** - Run multiple workers  
✓ **Large files** - No timeout issues  
✓ **Chunked data** - Automatic text splitting  
✓ **Batch embedding** - Efficient processing (50 chunks/batch)  
✓ **Error tracking** - Full error reporting  
✓ **Status polling** - Real-time job monitoring  

## 🔍 Supported File Formats

- PDF (.pdf)
- Word (.docx)
- Excel (.xlsx)
- PowerPoint (.pptx)
- Text (.txt, .csv, etc.)

## 📝 Example Usage

### Python
```python
import requests
import time

# Upload file
with open('document.pdf', 'rb') as f:
    r = requests.post(
        'http://localhost:8081/api/v1/upload-and-embed-queued',
        files={'file': f}
    )

job_id = r.json()['job_id']

# Poll status
while True:
    status = requests.get(
        f'http://localhost:8081/api/v1/job-status/{job_id}'
    ).json()
    
    print(f"Status: {status['status']}")
    
    if status['status'] == 'completed':
        print(f"✓ Created {status['chunks_created']} chunks")
        break
    elif status['status'] == 'failed':
        print(f"✗ Error: {status['error']}")
        break
    
    time.sleep(5)
```

### cURL
```bash
# Upload
JOB_ID=$(curl -X POST -F "file=@doc.pdf" \
  http://localhost:8081/api/v1/upload-and-embed-queued | jq -r '.job_id')

# Check status
curl http://localhost:8081/api/v1/job-status/$JOB_ID
```

## ⚙️ Configuration

In `app/config/settings.py`:

```python
CHUNK_SIZE = 512                              # Tokens per chunk
CHUNK_OVERLAP = 75                            # Overlap in tokens
EMBEDDING_MODEL = "models/gemini-embedding-001"  # Embedding model
REDIS_URL = "redis://localhost:6379"          # Redis connection
```

## 📊 Job Status Values

| Status | Meaning |
|--------|---------|
| `queued` | Waiting to be processed |
| `started` | Processing in progress |
| `completed` | Successfully finished |
| `failed` | Processing failed (check error) |

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Worker not processing | Ensure `python worker.py` is running |
| "Unsupported format" | Check file extension (pdf, docx, xlsx, pptx, txt) |
| Job stuck in "queued" | Check Redis is running, worker is active |
| Long processing time | Normal for large files; check worker logs |

## 📚 Full Documentation

See **UPLOAD_QUEUE_DOCUMENTATION.md** for:
- Detailed architecture overview
- Production deployment guides
- Monitoring and scaling strategies
- Advanced configurations

## ✨ What's Different?

### Old Endpoint (Still Available)
- **POST /upload-and-embed** - Synchronous, blocks until complete
- Good for small files
- Returns all results immediately
- May timeout on large files

### New Endpoint
- **POST /upload-and-embed-queued** - Asynchronous, returns immediately
- Good for all file sizes
- Returns job_id for status polling
- Can handle multiple large files concurrently
- Better user experience

---

**You're all set!** Start the worker process and your upload endpoint can now handle large files with chunking and embedding in the background. 🎉
