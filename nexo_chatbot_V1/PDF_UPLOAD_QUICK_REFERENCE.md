# PDF Upload - Quick Reference Guide

## ❓ Your Questions Answered

### 1️⃣ "How much size should the uploaded PDF be?"

**Answer: Maximum 100 MB**

```python
# Configuration in app/config/settings.py
MAX_FILE_SIZE_MB: int = 100
MAX_FILE_SIZE_BYTES: int = 104,857,600  # 100 MB

# Accepted sizes
✓ 1 MB     → Small document
✓ 10 MB    → Medium document  
✓ 50 MB    → Large document
✓ 100 MB   → Maximum limit
✗ 150 MB   → REJECTED (exceeds limit)
```

### 2️⃣ "Will the data be converted to vectors?"

**Answer: YES, Completely**

Every chunk of your PDF is converted to a **vector** (array of 3,072 numbers representing the meaning).

```
PDF Text: "Machine learning is a subset of AI"
    ↓
    Embedding Model (Gemini)
    ↓
Vector: [0.042, -0.156, 0.891, ..., 0.234]  ← 3,072 dimensions
```

**Benefits:**
- ✅ Enables **semantic search** (find by meaning, not keywords)
- ✅ Similar content = similar vectors
- ✅ Machine learning friendly
- ✅ Enables AI chatbot responses

### 3️⃣ "Will vectors be stored in vector DB?"

**Answer: YES, in Qdrant**

Vectors are stored in **Qdrant** vector database with metadata:

```
Qdrant Collection: domain_docs
├─ Total Points: 45 (one per chunk)
├─ Vector Dimension: 3,072
├─ Storage: Persistent (survives restarts)
└─ Query Capability: Semantic search enabled
```

Each stored vector includes:
```python
{
    "id": "unique-uuid",
    "vector": [0.042, -0.156, 0.891, ..., 0.234],
    "metadata": {
        "content": "Original chunk text",
        "source": "uploaded_file",
        "url": "filename.pdf"
    }
}
```

### 4️⃣ "Will vectors be separated and checked?"

**Answer: YES, with Full Verification**

---

## 🔄 COMPLETE PROCESSING FLOW

```
┌─────────────────────────────────────────────┐
│  PDF UPLOAD (e.g., 8 MB file)               │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
    ┌─ STEP 1: FILE SIZE VALIDATION ─┐
    │ Check: Size < 100 MB            │
    │ Result: 8 MB < 100 MB ✓         │
    │ Verification: ✓ PASSED          │
    └────────────────┬────────────────┘
                     │
                     ▼
    ┌─ STEP 2: TEXT EXTRACTION ─┐
    │ Extract from PDF            │
    │ Result: 450,000 characters  │
    │ Verification: ✓ EXTRACTED   │
    └────────────────┬────────────┘
                     │
                     ▼
    ┌─ STEP 3: TEXT CLEANING ─┐
    │ Remove boilerplate          │
    │ Result: 385,000 characters  │
    │ Reduction: 14.4%            │
    │ Verification: ✓ CLEANED     │
    └────────────────┬────────────┘
                     │
                     ▼
    ┌─ STEP 4: CHUNKING (DATA SEPARATION) ─┐
    │ Split into chunks: 512 tokens each    │
    │ With overlap: 75 tokens               │
    │ Result: 89 separate chunks            │
    │ Verification: ✓ CHUNKS CREATED       │
    │                                        │
    │ Chunk 1: "The document discusses..."  │
    │ Chunk 2: "...AI and machine learning" │
    │ Chunk 3: "...learning models require" │
    │ ... (86 more chunks)                  │
    └────────────────┬────────────────────┘
                     │
                     ▼
    ┌─ STEP 5: VECTOR GENERATION ─┐
    │ Convert each chunk to vector  │
    │ Using: Gemini Embedding API   │
    │ Dimension: 3,072 per vector   │
    │ Result: 89 vectors generated  │
    │ Verification: ✓ VECTORS OK    │
    │                               │
    │ Chunk 1 ──→ Vector 1          │
    │   [0.042, -0.156, 0.891, ...] │
    │ Chunk 2 ──→ Vector 2          │
    │   [0.156, 0.234, -0.567, ...] │
    │ ... (87 more vectors)         │
    └────────────────┬──────────────┘
                     │
                     ▼
    ┌─ STEP 6: VECTOR STORAGE ─────┐
    │ Store in Qdrant Database      │
    │ Batch 1: 50 chunks → 50 vecs  │
    │ Batch 2: 39 chunks → 39 vecs  │
    │ Total: 89 points stored       │
    │ Verification: ✓ STORED        │
    │                               │
    │ Point 1:                      │
    │  ID: uuid-1                   │
    │  Vector: [0.042, -0.156, ...]  │
    │  Content: "The document..."   │
    │ Point 2:                      │
    │  ID: uuid-2                   │
    │  Vector: [0.156, 0.234, ...]   │
    │  Content: "...AI and ML"      │
    │ ... (87 more points)          │
    └────────────────┬──────────────┘
                     │
                     ▼
    ┌─ STATUS: COMPLETED ─┐
    │ ✓ All checks passed  │
    │ ✓ Vectors searchable │
    │ Ready for queries    │
    └──────────────────────┘
```

---

## ✅ VERIFICATION CHECKS

### All 7 Verification Steps:

| # | Step | Check | Result |
|---|------|-------|--------|
| 1 | Size | File < 100 MB | ✓ PASSED |
| 2 | Format | PDF supported | ✓ PASSED |
| 3 | Extraction | Text extracted | ✓ PASSED (450K chars) |
| 4 | Cleaning | Boilerplate removed | ✓ PASSED (14.4% reduction) |
| 5 | Chunking | Data separated into chunks | ✓ PASSED (89 chunks) |
| 6 | Vectors | Generated embeddings | ✓ PASSED (89 vectors × 3072 dims) |
| 7 | Storage | Stored in Qdrant | ✓ PASSED (89 points indexed) |

### Verification Response Example:

```json
{
  "status": "completed",
  "verification_checks": {
    "size_validation": "✓ PASSED (8,912,896 bytes < 104,857,600 limit)",
    "format_validation": "✓ PASSED (PDF)",
    "text_extraction": "✓ PASSED (450,000 characters)",
    "text_cleaning": "✓ PASSED (385,000 chars, 14.4% reduction)",
    "chunking": "✓ PASSED (89 chunks created)",
    "vector_generation": "✓ PASSED (89 vectors generated)",
    "vector_storage": "✓ PASSED (89 vectors stored in Qdrant)"
  }
}
```

---

## 🧪 HOW TO VERIFY

### Option 1: API Endpoints

**Check Upload Status**
```bash
curl http://localhost:8081/api/v1/job-status/{job_id}
```

**Check Vectors in Database**
```bash
curl http://localhost:8081/api/v1/verify/vectors
```

### Option 2: Verification Script
```bash
python verify_pdf_upload.py your_file.pdf
```

This script will:
- ✓ Upload the PDF
- ✓ Monitor processing
- ✓ Verify vectors are stored
- ✓ Show detailed logs

### Option 3: Check Logs

```
[job-123] File Size: 8,912,896 bytes (8.50 MB)
[job-123] ✓ File size validation passed

[job-123] ✓ Text extraction successful: 450,000 characters
[job-123] ✓ Text cleaned: 385,000 chars, 14.4% reduction

[job-123] ✓ Chunking successful: 89 chunks created
[job-123]   - Average chunk size: 4,326 characters

[job-123] ✓ Generated 89 vectors with dimension 3072
[job-123] ✓ Batch 1 indexed: 50 chunks → 50 vectors stored
[job-123] ✓ Batch 2 indexed: 39 chunks → 39 vectors stored

[job-123] ✓ UPLOAD PROCESSING COMPLETED SUCCESSFULLY
```

---

## 📊 WHAT ACTUALLY HAPPENS

### Before Upload
```
Your PDF: 8 MB file
Status: Not in system
```

### After Upload (Queued)
```
Job Status: queued
Action: Waiting in queue
Timing: Seconds
Vector Count: 0
```

### During Processing
```
Job Status: started
Phases:
  1. Extract: 450K chars
  2. Clean: 385K chars
  3. Chunk: 89 chunks
  4. Vector: 89 vectors
  5. Store: In progress...
Timing: Minutes (depends on file size)
Vector Count: 0-89 (incrementally)
```

### After Completion
```
Job Status: completed
File Size: 8,912,896 bytes
Text Extracted: 450,000 characters
Text Cleaned: 385,000 characters
Chunks Created: 89
Chunks Indexed: 89
Vectors Generated: 89
Vectors Stored: 89 (in Qdrant)
Vector Dimension: 3,072
Embedding Model: Gemini
```

---

## 🔍 DATA SEPARATION VERIFICATION

### How Data is Separated:

1. **By Chunks** (during chunking):
   ```
   Chunk 1: Tokens 1-512
   Chunk 2: Tokens 437-949 (75 overlap)
   Chunk 3: Tokens 874-1386 (75 overlap)
   ...
   ```

2. **By Vectors** (during embedding):
   ```
   Vector 1: [0.042, -0.156, 0.891, ...] (3072 dims)
   Vector 2: [0.156, 0.234, -0.567, ...] (3072 dims)
   Vector 3: [0.234, 0.567, 0.234, ...] (3072 dims)
   ...
   ```

3. **In Database** (after storage):
   ```
   Point 1: ID uuid-1, Vector 1, Content 1
   Point 2: ID uuid-2, Vector 2, Content 2
   Point 3: ID uuid-3, Vector 3, Content 3
   ...
   ```

### Separation Checks:

- ✅ Each chunk has unique ID
- ✅ Each vector has unique 3,072 dimensions
- ✅ Each point in database has unique UUID
- ✅ Chunk count = Vector count = Stored points count
- ✅ No duplicate vectors
- ✅ All vectors properly indexed for search

---

## ⚙️ CONFIGURATION

```python
# File Upload Limits
MAX_FILE_SIZE_MB = 100              # 100 MB maximum

# Chunking (Data Separation)
CHUNK_SIZE = 512                    # tokens per chunk
CHUNK_OVERLAP = 75                  # token overlap

# Embedding (Vector Generation)
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 3072                # dimensions per vector

# Batch Processing (For Efficiency)
EMBED_BATCH_SIZE = 50               # vectors per batch

# Vector Database
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_COLLECTION = "domain_docs"
```

---

## 🚀 QUICK START

### 1. Start Services
```bash
# Terminal 1: API
python -m uvicorn app.main:app --port 8081

# Terminal 2: Worker
python worker.py

# Terminal 3: Redis & Qdrant
docker-compose up -d
```

### 2. Upload PDF
```bash
# Using curl
curl -X POST -F "file=@your_file.pdf" \
  http://localhost:8081/api/v1/upload-and-embed-queued

# Returns job_id
```

### 3. Monitor Processing
```bash
# Check status
curl http://localhost:8081/api/v1/job-status/{job_id}

# Or use verification script
python verify_pdf_upload.py your_file.pdf
```

### 4. Verify Vectors
```bash
# Check vectors in database
curl http://localhost:8081/api/v1/verify/vectors
```

### 5. Use in Chat
```bash
# Query the uploaded PDF content
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What does the PDF say about machine learning?"}'
```

---

## ❌ TROUBLESHOOTING

| Issue | Cause | Solution |
|-------|-------|----------|
| "File exceeds 100 MB" | PDF too large | Split PDF or increase limit |
| "No vectors in DB" | Job not completed | Wait longer or check job status |
| "Vector dimension mismatch" | Model conflict | Restart all services |
| "Connection refused" | Service not running | Check API, worker, Redis, Qdrant |
| "Chunks = 0" | No text in PDF | Check if PDF has readable text |

---

## ✨ SUMMARY

**✓ Size Limit:** 100 MB per PDF

**✓ Vector Conversion:** YES - All text → vectors (3,072 dimensions)

**✓ Storage:** YES - All vectors → Qdrant database

**✓ Separation:** YES - Data split into chunks → vectors → database points

**✓ Verification:** YES - 7 checks at each step, full logging

**✓ Searchability:** YES - Vectors enable semantic search

---

**You're all set!** Your PDFs will be properly chunked, converted to vectors, stored in Qdrant, and fully verified. 🎉
