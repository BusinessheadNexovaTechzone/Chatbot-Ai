# PDF Upload Verification Guide

## 📋 Overview
This guide explains exactly what happens when you upload a PDF file, how the data is converted to vectors, and how vectors are separated and stored in the vector database.

---

## 1️⃣ FILE SIZE VALIDATION

### What Happens
When you upload a PDF, the first check is **file size validation**.

### Configuration
```python
# In app/config/settings.py
MAX_FILE_SIZE_MB: int = 100                 # Maximum: 100 MB
MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB = 104,857,600 bytes
```

### Acceptable PDF Sizes
| Size | Status |
|------|--------|
| < 100 MB | ✅ Accepted |
| ≥ 100 MB | ❌ Rejected |

### Error Example
```json
{
  "status": "failed",
  "error": "File size 250000000 bytes exceeds maximum 104857600 bytes (100 MB)"
}
```

### Logs
```
[job-123] File Size: 5,242,880 bytes (5.00 MB)
[job-123] ✓ File size validation passed: 5,242,880 bytes
```

---

## 2️⃣ TEXT EXTRACTION FROM PDF

### What Happens
The PDF is processed to **extract readable text**. This handles:
- PDF structure parsing
- Text encoding detection
- Special character handling
- Table/image metadata

### Supported Formats (Beyond PDF)
```python
SUPPORTED_FORMATS = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".xlsx": "Excel",
    ".pptx": "PowerPoint",
    ".txt": "Text",
    ".csv": "CSV",
}
```

### Example Extraction
```
Original PDF: 5 MB file with 50 pages
↓
Extracted Text: 250,000 characters
```

### Logs
```
[job-123] STEP 3: Extracting text from file...
[job-123] ✓ Text extraction successful: 250,000 characters
```

---

## 3️⃣ TEXT CLEANING & NORMALIZATION

### What Happens
Raw extracted text is **cleaned and normalized**:

1. **Remove boilerplate** - Headers, footers, navigation
2. **Normalize whitespace** - Remove extra spaces/newlines
3. **Fix encoding issues** - Handle special characters
4. **Remove duplicates** - Eliminate repeated content

### Example Processing
```
Before Cleaning: 250,000 characters
    - Boilerplate headers: -15,000 chars
    - Extra whitespace: -10,000 chars
    - Navigation text: -8,000 chars
    
After Cleaning: 217,000 characters
```

### Statistics
```
Extracted: 250,000 characters
Cleaned: 217,000 characters
Reduction: 13.2% (boilerplate removed)
```

### Logs
```
[job-123] STEP 4: Cleaning and normalizing text...
[job-123] ✓ Text cleaned: 217,000 chars, 13.2% reduction
```

---

## 4️⃣ TEXT CHUNKING - DATA SEPARATION

### What Happens ✨ KEY STEP
Clean text is **split into smaller chunks** to enable vector generation and semantic search.

### Configuration
```python
CHUNK_SIZE: int = 512          # Target tokens per chunk
CHUNK_OVERLAP: int = 75        # Overlap between chunks
```

### Chunking Algorithm
```
1. Split text by sentence boundaries (. ! ?)
2. Group sentences until reaching 512 tokens
3. Add 75-token overlap with previous chunk
4. Create separate, searchable units
```

### Example Chunking
```
Original cleaned text: 217,000 characters

↓ Split with overlap

Chunk 1:
  "The document discusses artificial intelligence. AI is..."
  [512 tokens, ID: uuid-1]

Chunk 2:
  "...intelligence and machine learning. Machine learning..."
  [512 tokens, 75 token overlap with Chunk 1, ID: uuid-2]

Chunk 3:
  "...learning models require large datasets. Datasets must..."
  [512 tokens, 75 token overlap with Chunk 2, ID: uuid-3]

... and so on ...
```

### Chunk Statistics
```
Total chunks created: 45
Average chunk size: 4,822 characters
Min chunk size: 2,100 characters
Max chunk size: 6,500 characters
```

### Why Chunking Matters
✅ **Enables semantic search** - Search by meaning, not keywords  
✅ **Improves relevance** - Smaller units = more precise results  
✅ **Manages size** - Embedding models have input limits  
✅ **Preserves context** - Overlap maintains continuity  

### Logs
```
[job-123] STEP 5: Splitting text into chunks...
[job-123] ✓ Chunking successful: 45 chunks created
[job-123]   - Average chunk size: 4,822 characters
[job-123]   - Min chunk size: 2,100 characters
[job-123]   - Max chunk size: 6,500 characters
```

---

## 5️⃣ VECTOR GENERATION - DATA TO VECTORS

### What Happens ✨ KEY STEP
Each chunk is **converted to a vector** (array of numbers representing meaning).

### Embedding Models
```python
# Option 1: Google Gemini (Recommended)
EMBEDDING_MODEL: str = "models/gemini-embedding-001"
EMBEDDING_DIM: int = 3072
Result: Dense vector with 3,072 dimensions

# Option 2: Local Model (Fallback)
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
EMBEDDING_DIM: int = 384
Result: Dense vector with 384 dimensions
```

### Example Vector Conversion
```
Chunk Text:
  "Machine learning is a subset of artificial intelligence
   that enables systems to learn from data."

↓ Embedding Generation ↓

Vector (3072 dimensions):
  [0.042, -0.156, 0.891, ..., 0.234]
  
This vector CAPTURES THE MEANING of the chunk.
Similar chunks = similar vectors (closer in space)
```

### Batch Processing
```
Configuration: EMBED_BATCH_SIZE = 50

Processing 45 chunks:
- Batch 1: chunks 1-45 (45 chunks total)
- Send all texts to embedding model
- Get 45 vectors back
- Each vector: 3,072 dimensions
```

### Verification Checks
```python
# Verify embedding count matches chunks
if len(embeddings) != len(texts):
    raise ValueError("Embedding mismatch!")

# Verify each vector has correct dimension
for embedding in embeddings:
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError("Dimension mismatch!")
```

### Logs
```
[job-123] STEP 6: Generating embeddings (vectors) and storing...
[job-123] Embedding model: models/gemini-embedding-001
[job-123] Embedding dimension: 3072
[job-123] Batch size: 50 chunks per batch
[job-123] ► Processing batch 1/1 (45 chunks)...
[job-123]   Generating embeddings for 45 texts...
[job-123]   ✓ Generated 45 vectors with dimension 3072
```

---

## 6️⃣ VECTOR STORAGE & INDEXING

### What Happens ✨ KEY STEP
Generated vectors are **stored in Qdrant vector database** with metadata.

### Vector Database: Qdrant
```
Qdrant Configuration:
├─ Host: localhost
├─ Port: 6333
├─ Collection: domain_docs
├─ Vectors per point: 1
└─ Vector dimension: 3072
```

### Data Structure Per Vector
```python
PointStruct(
    id="550e8400-e29b-41d4-a716-446655440000",  # Unique ID
    vector=[0.042, -0.156, 0.891, ..., 0.234],   # 3072 dimensions
    payload={
        "content": "Machine learning is a subset...",
        "source": "uploaded_file",
        "url": "document.pdf",
        "section": "main",
        "timestamp": "2026-04-22T10:30:00"
    }
)
```

### Storage Verification
```
Total Chunks: 45
↓ Generate Embeddings ↓
Total Vectors: 45 (one per chunk)
↓ Store in Qdrant ↓
Qdrant Collection Points: 45
```

### Separation/Checks During Storage
```python
# Each batch verification:

1. Verify chunk-vector pairing
   ✓ 45 chunks matched with 45 vectors

2. Verify vector dimensions
   ✓ All 45 vectors have 3072 dimensions

3. Verify payload metadata
   ✓ Each vector has content, source, url, section

4. Verify Qdrant upsert
   ✓ All 45 points successfully stored

5. Verify retrieval (spot check)
   ✓ Can retrieve vectors by ID and by semantic search
```

### Logs
```
[job-123] Connected to vector database: localhost:6333
[job-123] Vector collection: domain_docs
[job-123] ► Processing batch 1/1 (45 chunks)...
[job-123] ✓ Batch 1 indexed: 45 chunks → 45 vectors stored
[job-123] ✓ Vector generation and storage completed: 45 chunks indexed
```

---

## 📊 COMPLETE FLOW SUMMARY

```
PDF Upload (5 MB)
    ↓
[Step 1] File Size Validation
    ✓ 5 MB < 100 MB limit
    ↓
[Step 2] Text Extraction
    ✓ 250,000 characters extracted
    ↓
[Step 3] Text Cleaning
    ✓ 217,000 characters cleaned (13.2% reduction)
    ↓
[Step 4] Text Chunking (SEPARATION)
    ✓ 45 chunks created
    ├─ Chunk 1: 512 tokens, UUID-1
    ├─ Chunk 2: 512 tokens, UUID-2
    ├─ ...
    └─ Chunk 45: 256 tokens, UUID-45
    ↓
[Step 5] Vector Generation (DATA → VECTORS)
    ✓ 45 vectors generated
    ├─ Vector 1: [0.042, -0.156, ..., 0.234] (3072 dims)
    ├─ Vector 2: [0.891, 0.245, ..., -0.123] (3072 dims)
    ├─ ...
    └─ Vector 45: [0.456, -0.789, ..., 0.567] (3072 dims)
    ↓
[Step 6] Qdrant Storage (VECTOR DB)
    ✓ 45 vectors stored
    ├─ Point 1: Vector + Metadata (source, content, url)
    ├─ Point 2: Vector + Metadata (source, content, url)
    ├─ ...
    └─ Point 45: Vector + Metadata (source, content, url)
    ↓
✓ COMPLETED
  - Status: success
  - Chunks Created: 45
  - Chunks Indexed: 45
  - Vectors Generated: 45
  - Vectors Stored: 45 (in Qdrant)
```

---

## 🔍 VERIFICATION ENDPOINTS

### Check Upload Job Status
```bash
curl http://localhost:8081/api/v1/job-status/{job_id}
```

**Response includes:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "file_size": 5242880,
  "extracted_chars": 250000,
  "cleaned_chars": 217000,
  "chunks_created": 45,
  "chunks_indexed": 45,
  "vectors_generated": 45,
  "verification_checks": {
    "size_validation": "✓ PASSED (5,242,880 bytes < 104,857,600 bytes limit)",
    "format_validation": "✓ PASSED (PDF)",
    "text_extraction": "✓ PASSED (250,000 characters extracted)",
    "text_cleaning": "✓ PASSED (217,000 chars, 13.2% reduction)",
    "chunking": "✓ PASSED (45 chunks created)",
    "vector_generation": "✓ PASSED (45 vectors generated)",
    "vector_storage": "✓ PASSED (45 vectors stored in Qdrant)"
  }
}
```

### Verify Vectors in Database
```bash
curl http://localhost:8081/api/v1/verify/vectors
```

**Response:**
```json
{
  "collection_name": "domain_docs",
  "total_vectors": 45,
  "embedding_dimension": 3072,
  "embedding_model": "models/gemini-embedding-001",
  "sample_vectors": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "vector_dimension": 3072,
      "source": "uploaded_file",
      "url": "document.pdf",
      "content_preview": "Machine learning is a subset of artificial intelligence that..."
    }
  ],
  "storage_status": "✓ VERIFIED"
}
```

---

## 📈 EXAMPLE: REAL PDF PROCESSING

### PDF: "machine_learning_guide.pdf" (8.5 MB, 60 pages)

```
=== PROCESSING LOG ===

[job-abc123] File Size: 8,912,896 bytes (8.50 MB)
[job-abc123] ✓ File size validation passed

[job-abc123] STEP 3: Extracting text from file...
[job-abc123] ✓ Text extraction successful: 450,000 characters

[job-abc123] STEP 4: Cleaning and normalizing text...
[job-abc123] ✓ Text cleaned: 385,000 chars, 14.4% reduction

[job-abc123] STEP 5: Splitting text into chunks...
[job-abc123] ✓ Chunking successful: 89 chunks created
[job-abc123]   - Average chunk size: 4,326 characters
[job-abc123]   - Min chunk size: 1,850 characters
[job-abc123]   - Max chunk size: 7,200 characters

[job-abc123] STEP 6: Generating embeddings and storing...
[job-abc123] ► Processing batch 1/2 (50 chunks)...
[job-abc123]   ✓ Generated 50 vectors with dimension 3072
[job-abc123] ✓ Batch 1 indexed: 50 chunks → 50 vectors stored

[job-abc123] ► Processing batch 2/2 (39 chunks)...
[job-abc123]   ✓ Generated 39 vectors with dimension 3072
[job-abc123] ✓ Batch 2 indexed: 39 chunks → 39 vectors stored

[job-abc123] ========================================
[job-abc123] ✓ UPLOAD PROCESSING COMPLETED SUCCESSFULLY
[job-abc123] Summary:
[job-abc123]   - File Size: 8,912,896 bytes (8.50 MB)
[job-abc123]   - Extracted: 450,000 characters
[job-abc123]   - Cleaned: 385,000 characters
[job-abc123]   - Chunks Created: 89
[job-abc123]   - Chunks Indexed: 89
[job-abc123]   - Vectors Generated & Stored: 89
[job-abc123]   - Embedding Dimension: 3072
[job-abc123] ========================================
```

---

## ✅ VERIFICATION CHECKLIST

After upload, verify:

- [ ] File size ≤ 100 MB
- [ ] PDF format is supported (`.pdf`)
- [ ] Text extracted (> 1000 characters)
- [ ] Text cleaned (boilerplate removed)
- [ ] Chunks created (count > 0)
- [ ] Vectors generated (count = chunk count)
- [ ] Vectors stored in Qdrant (count = chunk count)
- [ ] Vector dimension correct (3072 for Gemini)
- [ ] Metadata present (source, url, content)
- [ ] Job status shows "completed"

---

## 🆘 TROUBLESHOOTING

| Issue | Cause | Solution |
|-------|-------|----------|
| "File size exceeds maximum" | PDF > 100 MB | Reduce PDF size or increase limit in settings |
| "Could not extract text" | PDF is scanned/image-only | Use OCR or convert to text first |
| "Chunks created: 0" | Extracted text too small | Check if text actually exists in PDF |
| "Vectors not stored" | Qdrant not running | Ensure `docker-compose up -d qdrant` |
| "Vector dimension mismatch" | Model changed mid-process | Restart services, check EMBEDDING_DIM |

---

## 📚 CONFIGURATION DEFAULTS

```python
# app/config/settings.py

# File Upload
MAX_FILE_SIZE_MB = 100
MAX_FILE_SIZE_BYTES = 104,857,600

# Chunking
CHUNK_SIZE = 512 tokens
CHUNK_OVERLAP = 75 tokens

# Embedding
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 3072

# Batch Processing
EMBED_BATCH_SIZE = 50

# Vector Database
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_COLLECTION = "domain_docs"
```

---

**Summary:** When you upload a PDF, it undergoes 6 transformation steps, creating properly separated chunks that are converted to vectors and securely stored in your vector database with full metadata! ✅
