# Production-Ready AI Chatbot Implementation Guide

## Overview

Your FastAPI chatbot has been enhanced with the following production-ready features:

✅ **Configurable Assistant Naming** - Set custom assistant name (e.g., "John", "Emma")  
✅ **Conversation Memory** - Session-based history with MongoDB  
✅ **Intent Classification** - Automatic routing (domain/web/general)  
✅ **Document Retrieval** - Vector search via Qdrant  
✅ **Streaming Responses** - Real-time token-by-token delivery  
✅ **OpenAI Integration** - gpt-4o-mini + embeddings  
✅ **Caching** - Redis response cache for fast lookups  
✅ **WebSocket Support** - Real-time bidirectional chat  

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Backend                      │
├─────────────────────────────────────────────────────────┤
│ POST /api/v1/chat          → Non-streaming chat        │
│ POST /api/v1/chat/stream   → SSE streaming             │
│ WS /v1/ws/web_chat/{sid}   → WebSocket real-time       │
│ POST /api/v1/upload        → File upload (PDF, DOCX)   │
│ POST /api/v1/ingest        → Website scraping          │
└─────────────────────────────────────────────────────────┘
                     ↓
┌──────────────┬──────────────┬──────────────┐
│   MongoDB    │    Redis     │   Qdrant     │
│   (History)  │   (Cache)    │  (Vectors)   │
└──────────────┴──────────────┴──────────────┘
                     ↓
               ┌──────────────┐
               │  OpenAI API  │
               │ (LLM + Emb)  │
               └──────────────┘
```

---

## Key Features

### 1. Configurable Assistant Name

The assistant can now be named anything you want. The name is used in:
- System prompt introduction
- Natural conversation responses
- Proper handling of name-based queries

**Request Example:**
```json
{
  "query": "What is your name?",
  "session_id": "user_123",
  "assistant_name": "John",
  "stream": false
}
```

**Response Example:**
```json
{
  "answer": "I am John, your AI assistant. How can I help you today?",
  "assistant_name": "John",
  "intent": "general",
  "sources": [],
  "confidence": 0.95,
  "latency_ms": 342.5,
  "cached": false
}
```

### 2. Conversation Memory

Sessions are automatically persisted in MongoDB with encryption.

**How It Works:**
1. Client sends `session_id` (UUID for web, phone number for WhatsApp)
2. Backend fetches last 6 exchanges from MongoDB
3. Context included in system prompt for coherent responses
4. New messages automatically saved after generation

**Example Flow:**
```
User Q1: "My name is Dinesh"
→ Saved: session_id, encrypted_query, encrypted_response

User Q2: "What is my name?"
→ Fetches history
→ System sees previous exchange
→ Responds: "Your name is Dinesh"
→ Saved to history

User Q3: "Who are you?"
→ Fetches history (includes previous messages)
→ Assistant responds as configured name (e.g., "I am John")
```

### 3. Intent Classification

Queries are automatically classified into three categories:

| Intent | Use Case | Example |
|--------|----------|---------|
| **GENERAL** | Common knowledge, facts, definitions | "What is .NET?", "Tell me a joke" |
| **DOMAIN** | Company-specific documents, FAQs | "Who is the CEO?", "What products do you offer?" |
| **WEB** | Real-time, current information | "What's the weather?", "Latest news" |

**Classification Process:**
1. Query sent to intent classifier
2. OpenAI classifies with confidence score
3. Routing logic selects appropriate handler
4. Results returned with intent and confidence

**Response includes:**
```json
{
  "intent": "domain",          // domain | web | general
  "confidence": 0.87,          // 0.0 - 1.0 classification confidence
  "sources": [                 // Retrieved documents (if domain intent)
    {
      "title": "Company Profile",
      "url": "docs/company.pdf",
      "snippet": "Founded in 2010..."
    }
  ]
}
```

### 4. Document Retrieval & RAG

When a domain query is detected:

1. **Query Embedding** → Convert query to vector using OpenAI embeddings
2. **Vector Search** → Search Qdrant with similarity threshold
3. **Reranking** → Cross-encoder reranking (top-3)
4. **Context Assembly** → Format chunks as prompt context
5. **LLM Generation** → OpenAI generates answer using context

**Confidence Scoring:**
- If top chunk score ≥ 0.65 AND intent confidence ≥ 0.60 → Use domain context
- Otherwise → Fallback to web search for better coverage

### 5. System Prompt Behavior

The system prompt dynamically includes the assistant name:

```python
BASE_SYSTEM_PROMPT = """You are a helpful AI assistant named {assistant_name}.

RULES:
1. If the user asks your name or who you are, respond naturally as {assistant_name}.
2. If domain context is provided, answer from that context only.
3. Use conversation history to maintain context.
...
"""
```

This ensures the assistant:
- Introduces itself correctly
- Responds properly to "Who are you?" questions
- Can be called by name in conversation
- Remembers conversation context

---

## API Reference

### POST /api/v1/chat

**Non-streaming chat endpoint.**

**Request:**
```json
{
  "query": "Who is the CEO of the company?",
  "session_id": "user_abc123",
  "assistant_name": "John",
  "stream": false
}
```

**Response:**
```json
{
  "answer": "The CEO is Satya Nadella.",
  "assistant_name": "John",
  "intent": "domain",
  "sources": [
    {
      "title": "Executive Team",
      "url": "docs/leadership.pdf",
      "snippet": "Satya Nadella, CEO..."
    }
  ],
  "confidence": 0.92,
  "latency_ms": 645.32,
  "cached": false,
  "token_usage": {
    "input_tokens": 245,
    "output_tokens": 18,
    "total_tokens": 263
  }
}
```

### POST /api/v1/chat/stream

**Streaming chat via Server-Sent Events (SSE).**

**Request:**
```json
{
  "query": "Tell me about cloud computing",
  "session_id": "user_abc123",
  "assistant_name": "John",
  "stream": true
}
```

**Response (Stream):**
```
data: Cloud
data:  computing
data:  is
data:  ...
data: [DONE]
```

**Client Implementation (JavaScript):**
```javascript
const eventSource = new EventSource('/api/v1/chat/stream?query=...&session_id=...&assistant_name=John');

eventSource.onmessage = (event) => {
  if (event.data === '[DONE]') {
    eventSource.close();
  } else {
    console.log(event.data);  // Token received
  }
};

eventSource.onerror = (error) => {
  console.error('Stream error:', error);
  eventSource.close();
};
```

### WS /v1/ws/web_chat/{session_id}

**WebSocket endpoint for real-time bidirectional chat.**

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8081/v1/ws/web_chat/user_abc123');
```

**Send Message:**
```javascript
ws.send(JSON.stringify({
  "query": "What is your name?",
  "assistant_name": "John"
}));
```

**Receive Streaming Response:**
```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'token') {
    console.log(data.data);  // Token
  } else if (data.type === 'result') {
    console.log(data.data);  // Final response object
  }
};
```

### POST /api/v1/upload

**Upload documents (PDF, DOCX, XLSX, PPTX, TXT, CSV).**

**Request:**
```bash
curl -X POST "http://localhost:8081/api/v1/upload" \
  -F "file=@company_handbook.pdf"
```

**Response:**
```json
{
  "filename": "company_handbook.pdf",
  "content_type": "application/pdf",
  "size": 2458624,
  "content": "...",
  "is_text": false
}
```

### POST /api/v1/ingest

**Scrape websites and index content into vector database.**

**Request:**
```json
{
  "urls": ["https://example.com", "https://example.com/about"],
  "site_name": "Example Company",
  "force_refresh": false
}
```

**Response:**
```json
{
  "status": "success",
  "pages_scraped": 15,
  "chunks_indexed": 342,
  "errors": []
}
```

---

## Configuration

### Environment Variables (.env)

```bash
# App
APP_NAME="Nexo Chatbot"
APP_VERSION="1.0.0"
DEBUG=false
HOST=0.0.0.0
PORT=8081

# OpenAI
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.1
LLM_MAX_RETRIES=3

# MongoDB
MONGODB_URL=mongodb+srv://...
MONGODB_DB=nexo
ENCRYPTION_KEY=your-encryption-key-here

# Qdrant Vector DB
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=domain_docs

# Redis Cache
REDIS_URL=redis://localhost:6379
CACHE_TTL_SECONDS=3600

# Retrieval
TOP_K=5
SIMILARITY_THRESHOLD=0.3
RERANK_TOP_N=3

# File Upload
MAX_FILE_SIZE_MB=10

# WebSocket
WS_TIMEOUT_SECONDS=120
```

---

## Code Implementation Details

### Models (app/models/schemas.py)

```python
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    stream: bool = False
    assistant_name: Optional[str] = Field(default="Assistant", max_length=50)

class ChatResponse(BaseModel):
    answer: str
    assistant_name: str = "Assistant"  # Echoed from request
    intent: Intent
    sources: List[Citation] = []
    confidence: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False
    token_usage: Optional[TokenUsage] = None
```

### System Prompt (app/services/llm_generator.py)

```python
BASE_SYSTEM_PROMPT = """You are a helpful AI assistant named {assistant_name}. 
Answer user questions clearly and precisely.

RULES:
1. If the user asks your name or who you are, respond naturally as {assistant_name}.
2. If domain context is provided, answer from that context only.
3. Use conversation history to maintain context.
...
"""

def _build_system_prompt(assistant_name: str = "Assistant") -> str:
    return BASE_SYSTEM_PROMPT.format(assistant_name=assistant_name)
```

### LLM Methods

All generation methods now accept `assistant_name`:

```python
async def generate(
    self,
    query: str,
    assistant_name: str = "Assistant",
    domain_chunks: Optional[List[DocumentChunk]] = None,
    conversation_history: Optional[List[dict]] = None,
) -> tuple[str, List[Citation], TokenUsage]:
    messages = self._build_messages(
        query=query,
        assistant_name=assistant_name,
        domain_chunks=domain_chunks,
        conversation_history=conversation_history,
    )
    # ... rest of implementation
```

### Orchestrator Routing (app/services/orchestrator.py)

```python
async def handle(self, request: ChatRequest) -> ChatResponse:
    # 1. Try cache
    # 2. Fetch conversation history
    # 3. Classify intent
    # 4. Route based on intent:
    #    - WEB: generate_with_search()
    #    - DOMAIN: generate() with chunks
    #    - GENERAL: generate() without chunks
    # 5. Save to MongoDB
    # 6. Return response with assistant_name
```

---

## Memory & Conversation Flow

### Session Storage

```
MongoDB Collection: chat_history
├── session_id: "user_abc123"
├── query: <encrypted>
├── response: <encrypted>
├── token_usage: { input_tokens, output_tokens, ... }
└── timestamp: 2026-05-11T10:30:00Z
```

### Memory Retrieval

When a new query arrives:

1. Fetch last 6 exchanges from MongoDB for the session
2. Decrypt queries and responses
3. Format as conversation history: `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`
4. Include in system prompt for context
5. Generate response considering full conversation

### Encryption

All stored messages are encrypted with Fernet (symmetric encryption) using `ENCRYPTION_KEY` from `.env`.

```python
# Save
encrypted_query = encrypt(query, settings.ENCRYPTION_KEY)
await mongo_service.save_chat(session_id, encrypted_query, encrypted_response)

# Retrieve
decrypted = decrypt(encrypted_query, settings.ENCRYPTION_KEY)
```

---

## Performance Optimization

### 1. Caching Strategy

- **Cache Key**: Query text
- **Cache Value**: Full response (JSON)
- **TTL**: 1 hour (configurable)
- **Fallback**: Graceful degradation on cache miss

```python
# Try cache first
cached = await cache_service.get("response", request.query)
if cached:
    return ChatResponse(**cached)
```

### 2. Vector Retrieval

- **Top-K**: 5 chunks retrieved
- **Reranking**: Top-3 reranked with cross-encoder
- **Threshold**: Min similarity of 0.65 for confident domain answers
- **Fallback**: Web search if low confidence

### 3. Streaming

- **SSE Stream**: Tokens streamed to client as they arrive
- **WebSocket**: Bidirectional real-time delivery
- **Timeout**: 120 seconds idle timeout

### 4. Async Operations

All I/O operations are fully asynchronous:
- OpenAI API calls via `asyncio.to_thread()`
- MongoDB queries via `motor` (async driver)
- Redis operations via `aioredis`
- Vector searches via `qdrant-client` async

---

## Example Usage Scenarios

### Scenario 1: Multi-turn Conversation

```
Session: user_dinesh_001

Turn 1:
User:      "My name is Dinesh Sharma"
Assistant: "Nice to meet you, Dinesh Sharma! How can I help you?"

Turn 2:
User:      "What is my name?"
Assistant: "Your name is Dinesh Sharma."
  → Memory: Previous turn is in context

Turn 3:
User:      "John, tell me about your company"
Assistant: "I am John, your AI assistant. [Company info based on documents]"
  → Assistant correctly identified as "John"
  → Conversation history maintained
```

### Scenario 2: Domain Question with Fallback

```
Query: "Who founded our company?"

Step 1: Intent Classification → DOMAIN (confidence: 0.88)
Step 2: Vector Search → Found 3 chunks about company founding
Step 3: Top Score: 0.68 (≥ 0.65 threshold) → USE DOMAIN CONTEXT
Step 4: Generate answer using retrieved chunks
Step 5: Return answer with sources

Response:
{
  "answer": "Our company was founded in 2005 by [Founder Name]...",
  "intent": "domain",
  "sources": [{"title": "Company History", "url": "docs/history.pdf", ...}],
  "confidence": 0.88
}
```

### Scenario 3: Low Confidence Fallback

```
Query: "What are the latest updates?"

Step 1: Intent Classification → DOMAIN (confidence: 0.55)
Step 2: Vector Search → Found 2 low-scoring chunks (0.42)
Step 3: Top Score: 0.42 (< 0.65 threshold) → FALLBACK TO WEB SEARCH
Step 4: Web search + generate answer
Step 5: Return answer with web sources

Response:
{
  "answer": "Recent updates include...",
  "intent": "domain",
  "sources": [{"title": "Blog", "url": "example.com/blog", ...}],
  "confidence": 0.55  // Confidence preserved from classification
}
```

### Scenario 4: Streaming Response

```javascript
const response = await fetch('/api/v1/chat/stream', {
  method: 'POST',
  body: JSON.stringify({
    query: "Explain machine learning",
    session_id: "user_123",
    assistant_name: "Alex",
    stream: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const text = decoder.decode(value);
  const lines = text.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const token = line.slice(6);
      console.log(token);  // Display token
    }
  }
}
```

---

## Troubleshooting

### Issue: Assistant name not appearing in response

**Solution**: Ensure `assistant_name` is sent in the request body with proper default value.

```json
{
  "query": "Who are you?",
  "assistant_name": "John"  // Must be included
}
```

### Issue: Conversation history not persisting

**Checklist:**
1. Is `session_id` being sent?
2. Is MongoDB connected? (Check `/v1/health`)
3. Is `ENCRYPTION_KEY` properly set?

### Issue: Document queries returning low quality results

**Optimization:**
1. Increase `TOP_K` from 5 to 10 in settings
2. Lower `SIMILARITY_THRESHOLD` from 0.65 to 0.5
3. Ensure documents are properly chunked (512 tokens default)
4. Check reranking is enabled (`RERANK_TOP_N=3`)

### Issue: Slow response times

**Optimization:**
1. Enable Redis caching (check `REDIS_URL`)
2. Reduce `MAX_TOKENS` from 2048 to 1024
3. Use lower `TOP_K` (5 instead of 10)
4. Enable response streaming for real-time feedback

---

## Testing

### Quick Test

```bash
curl -X POST "http://localhost:8081/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who are you?",
    "session_id": "test_123",
    "assistant_name": "Alice",
    "stream": false
  }'
```

### Expected Response

```json
{
  "answer": "I am Alice, your AI assistant. How can I help you today?",
  "assistant_name": "Alice",
  "intent": "general",
  "sources": [],
  "confidence": 0.95,
  "latency_ms": 342.5,
  "cached": false
}
```

---

## Production Deployment

### Docker Deployment

```bash
# Build
docker build -t nexo-chatbot:latest .

# Run with services
docker compose up -d

# Check health
curl http://localhost:8081/v1/health
```

### Environment Setup

```bash
# Create .env file
cp .env.example .env

# Update with production values
OPENAI_API_KEY=sk-...
MONGODB_URL=mongodb+srv://user:pass@cluster...
QDRANT_HOST=qdrant.production.com
ENCRYPTION_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
```

### Scaling Considerations

- **Load Balancing**: Use multiple FastAPI instances behind Nginx
- **Caching**: Redis cluster for distributed cache
- **Database**: MongoDB Atlas for managed MongoDB
- **Vector DB**: Qdrant Cloud for managed Qdrant
- **Queue**: RQ with Redis for background jobs

---

## Summary of Changes

### Files Modified:

1. **app/models/schemas.py**
   - Added `assistant_name` field to `ChatRequest`
   - Added `assistant_name` field to `ChatResponse`

2. **app/services/llm_generator.py**
   - Changed `SYSTEM_PROMPT` to `BASE_SYSTEM_PROMPT` template
   - Added `_build_system_prompt(assistant_name)` helper
   - Updated all `generate*` methods to accept `assistant_name`
   - Updated `_build_messages` to use dynamic system prompt

3. **app/services/orchestrator.py**
   - Updated all LLM generator calls to pass `assistant_name`
   - Updated `ChatResponse` creation to include `assistant_name`

4. **app/api/routes/chat.py**
   - Updated streaming endpoint to pass `assistant_name` to all generator calls
   - Preserved all existing logic and backward compatibility

### Backward Compatibility:

✅ All changes are backward compatible  
✅ `assistant_name` defaults to "Assistant" if not provided  
✅ Existing endpoints work unchanged  
✅ Existing functionality preserved  

---

## Next Steps

1. **Test with Your Data**
   - Upload your company documents
   - Test with various assistant names
   - Verify conversation memory works

2. **Customize System Prompt**
   - Edit `BASE_SYSTEM_PROMPT` in `llm_generator.py` as needed
   - Add specific instructions for your use case

3. **Deploy to Production**
   - Set up Docker containers
   - Configure MongoDB Atlas
   - Deploy Qdrant Cloud
   - Set up load balancing

4. **Monitor & Optimize**
   - Track latencies and cache hit rates
   - Adjust `TOP_K` and similarity thresholds
   - Fine-tune retrieval quality

---

## Support & Questions

For issues or questions, refer to:
- OpenAI API Docs: https://platform.openai.com/docs
- Qdrant Docs: https://qdrant.tech/documentation
- MongoDB Docs: https://docs.mongodb.com
- FastAPI Docs: https://fastapi.tiangolo.com

---

**Version:** 1.0.0  
**Last Updated:** May 11, 2026  
**Status:** ✅ Production Ready
