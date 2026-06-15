# Quick Start Guide - Production AI Chatbot with Assistant Naming

## 🚀 What's New

Your chatbot has been enhanced with production-ready features:

✅ **Configurable Assistant Name** - Name your assistant (e.g., "John", "Alice", "Emma")  
✅ **Conversation Memory** - Sessions remember previous messages  
✅ **Intelligent Intent Routing** - Automatic domain/web/general classification  
✅ **Vector-Based Retrieval** - Fast document search with Qdrant  
✅ **Streaming Responses** - Real-time token delivery  
✅ **OpenAI Integration** - gpt-4o-mini + embeddings  

---

## 📋 Prerequisites

Ensure all services are running:

```bash
# Start MongoDB, Redis, Qdrant, OpenAI credentials
docker compose up -d

# Or start locally
net start MongoDB
D:\Nexo\services\redis\redis-server.exe
D:\Nexo\services\qdrant\qdrant.exe
```

Verify services:
```bash
curl http://localhost:8081/v1/health
```

Expected output:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "redis": "ok",
    "mongodb": "ok",
    "qdrant": "ok"
  }
}
```

---

## 🏃 Quick Start - 5 Minutes

### Step 1: Start the Backend

```bash
cd C:\Users\Nexova\Downloads\nexo_chatbot_11_05_2026

# Activate virtual environment
.venv\Scripts\activate

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8081
INFO:     Starting Nexo Chatbot v1.0.0
INFO:     All services initialized
```

### Step 2: Test with curl

```bash
# Basic chat
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who are you?",
    "session_id": "test_user_001",
    "assistant_name": "John",
    "stream": false
  }'
```

Response:
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

### Step 3: Test Conversation Memory

```bash
# Turn 1: User introduces themselves
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "My name is Sarah",
    "session_id": "user_sarah_001",
    "assistant_name": "Emma"
  }' | jq .answer

# Turn 2: Ask assistant to recall the name
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is my name?",
    "session_id": "user_sarah_001",
    "assistant_name": "Emma"
  }' | jq .answer

# Output: "Your name is Sarah."
```

---

## 💬 API Endpoints

### POST /api/v1/chat

Non-streaming response.

```bash
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Tell me about cloud computing",
    "session_id": "user_123",
    "assistant_name": "John",
    "stream": false
  }'
```

### POST /api/v1/chat/stream

Streaming response (Server-Sent Events).

```bash
curl -X POST http://localhost:8081/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Explain artificial intelligence",
    "session_id": "user_123",
    "assistant_name": "John",
    "stream": true
  }'
```

### WS /v1/ws/web_chat/{session_id}

WebSocket for real-time bidirectional chat.

```bash
wscat -c ws://localhost:8081/v1/ws/web_chat/user_123
# Send: {"query": "Hello!", "assistant_name": "John"}
```

---

## 🔑 Key Implementation Details

### 1. Models Updated

**File:** `app/models/schemas.py`

```python
class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    assistant_name: Optional[str] = Field(default="Assistant", max_length=50)
    stream: bool = False

class ChatResponse(BaseModel):
    answer: str
    assistant_name: str = "Assistant"  # Echoed from request
    intent: Intent
    sources: List[Citation] = []
    # ... other fields
```

### 2. LLM Generator Updated

**File:** `app/services/llm_generator.py`

```python
# Dynamic system prompt based on assistant name
BASE_SYSTEM_PROMPT = """You are a helpful AI assistant named {assistant_name}.

RULES:
1. If the user asks your name, respond as {assistant_name}.
2. Use conversation history to maintain context.
3. If domain context is provided, answer from that context only.
"""

def _build_system_prompt(assistant_name: str = "Assistant") -> str:
    return BASE_SYSTEM_PROMPT.format(assistant_name=assistant_name)

class LLMGenerator:
    async def generate(
        self,
        query: str,
        assistant_name: str = "Assistant",  # NEW PARAMETER
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
    ) -> tuple[str, List[Citation], TokenUsage]:
        messages = self._build_messages(
            query=query,
            assistant_name=assistant_name,  # PASSED HERE
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
        )
        # ... rest of implementation
```

### 3. Orchestrator Updated

**File:** `app/services/orchestrator.py`

```python
class RetrievalOrchestrator:
    async def handle(self, request: ChatRequest) -> ChatResponse:
        # ... routing logic ...

        # Pass assistant_name to all generation methods
        answer, citations, token_usage = await llm_generator.generate(
            query=request.query,
            assistant_name=request.assistant_name,  # NEW
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
        )

        # Include in response
        response = ChatResponse(
            answer=answer,
            assistant_name=request.assistant_name,  # NEW
            intent=intent_result.intent,
            sources=citations,
            # ... other fields
        )
```

### 4. Chat Routes Updated

**File:** `app/api/routes/chat.py`

```python
# Streaming endpoints now pass assistant_name
async for token in llm_generator.generate_stream(
    query=request.query,
    assistant_name=request.assistant_name,  # NEW
    domain_chunks=domain_chunks,
    conversation_history=conversation_history,
):
    full_response += token
    yield f"data: {token}\n\n"
```

---

## 🧠 Conversation Memory Flow

```
┌─────────────────────────────────────┐
│ User Sends Query with session_id    │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ MongoDB: Fetch last 6 messages      │
│ (Decrypt with ENCRYPTION_KEY)       │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Build System Prompt with            │
│ assistant_name + history            │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Send to OpenAI with full context    │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Receive Response from OpenAI        │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Save to MongoDB (encrypted)         │
│ - session_id                        │
│ - encrypted_query                   │
│ - encrypted_response                │
│ - timestamp                         │
└─────────────────────────────────────┘
```

---

## 📊 Example: Multi-Turn Conversation

### Session: user_david_001

**Turn 1:**
```json
{
  "query": "My name is David Chen",
  "session_id": "user_david_001",
  "assistant_name": "Alex"
}
```
Response: "Nice to meet you, David! I'm Alex, your AI assistant."

**Turn 2:**
```json
{
  "query": "What's my name again?",
  "session_id": "user_david_001",
  "assistant_name": "Alex"
}
```
Response: "Your name is David Chen." ← Memory working!

**Turn 3:**
```json
{
  "query": "Who are you?",
  "session_id": "user_david_001",
  "assistant_name": "Alex"
}
```
Response: "I am Alex, your AI assistant. We've been chatting and I remember that your name is David Chen."

---

## 🛠️ Configuration

### app/config/settings.py

```python
# App
APP_NAME: str = "Nexo Chatbot"
APP_VERSION: str = "1.0.0"

# OpenAI
OPENAI_API_KEY: Optional[str] = None  # Set via .env
LLM_MODEL: str = "gpt-4o-mini"
LLM_TEMPERATURE: float = 0.1

# MongoDB (for conversation history)
MONGODB_URL: str = "mongodb+srv://..."
MONGODB_DB: str = "nexo"
ENCRYPTION_KEY: str = "..."  # For encrypting messages at rest

# Qdrant (for document retrieval)
QDRANT_HOST: str = "localhost"
QDRANT_COLLECTION: str = "domain_docs"

# Redis (for response caching)
REDIS_URL: str = "redis://localhost:6379"
CACHE_TTL_SECONDS: int = 3600

# Retrieval
TOP_K: int = 5  # Number of chunks to retrieve
SIMILARITY_THRESHOLD: float = 0.65  # Min confidence for domain retrieval
```

---

## 📁 File Changes Summary

| File | Changes |
|------|---------|
| `app/models/schemas.py` | Added `assistant_name` field to ChatRequest and ChatResponse |
| `app/services/llm_generator.py` | Made system prompt dynamic based on assistant_name |
| `app/services/orchestrator.py` | Pass assistant_name to all LLM generation calls |
| `app/api/routes/chat.py` | Pass assistant_name to streaming endpoints |

✅ **All changes are backward compatible**  
✅ `assistant_name` defaults to "Assistant" if not provided  
✅ Existing functionality completely preserved  

---

## 📚 Code Examples

### Python Client

```python
import asyncio
from httpx import AsyncClient

async def chat():
    async with AsyncClient() as client:
        response = await client.post(
            "http://localhost:8081/api/v1/chat",
            json={
                "query": "What is your name?",
                "session_id": "user_123",
                "assistant_name": "John"
            }
        )
        print(response.json())

asyncio.run(chat())
```

### JavaScript Client

```javascript
const response = await fetch('http://localhost:8081/api/v1/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: 'Tell me a joke',
    session_id: 'user_123',
    assistant_name: 'John'
  })
});

const data = await response.json();
console.log(data.answer);  // "Why did the developer go broke? ..."
console.log(data.assistant_name);  // "John"
```

### React Component

```jsx
function ChatBot() {
  const [input, setInput] = useState('');
  const [response, setResponse] = useState('');
  const [sessionId] = useState(uuid());
  const assistantName = 'Emma';

  const handleSend = async () => {
    const res = await fetch('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: input,
        session_id: sessionId,
        assistant_name: assistantName,
        stream: false
      })
    });
    
    const data = await res.json();
    setResponse(data.answer);
    setInput('');
  };

  return (
    <div>
      <div>{assistantName}: {response}</div>
      <input value={input} onChange={e => setInput(e.target.value)} />
      <button onClick={handleSend}>Send</button>
    </div>
  );
}
```

---

## 🧪 Testing Checklist

- [ ] Start backend: `uvicorn app.main:app --reload`
- [ ] Health check: `curl http://localhost:8081/v1/health`
- [ ] Basic chat: `curl -X POST http://localhost:8081/api/v1/chat ...`
- [ ] Test assistant name in response
- [ ] Test conversation memory (Turn 1 → Turn 2)
- [ ] Test streaming: `curl -X POST http://localhost:8081/api/v1/chat/stream ...`
- [ ] Test WebSocket connection
- [ ] Check MongoDB: `db.chat_history.find({"session_id": "test"})`
- [ ] Check Redis cache: `redis-cli get response:...`
- [ ] Upload a document
- [ ] Test domain retrieval

---

## 🚨 Troubleshooting

### Assistant name not showing in response
✅ Check that `assistant_name` is in the request JSON  
✅ Verify it's not empty  

### Conversation memory not working
✅ Is `session_id` being sent?  
✅ Check MongoDB connection: `curl http://localhost:8081/v1/health`  
✅ Verify `ENCRYPTION_KEY` is set in .env  

### Slow responses
✅ Enable response caching (Redis)  
✅ Check Qdrant is running  
✅ Reduce `LLM_MAX_TOKENS` from 2048 to 1024  
✅ Use streaming mode for better UX  

### Documents not being found
✅ Check Qdrant has data: `curl http://localhost:6333/collections/domain_docs`  
✅ Lower `SIMILARITY_THRESHOLD` from 0.65 to 0.5  
✅ Upload more documents for better coverage  

---

## 📖 Complete Documentation

For detailed information, see:
- **[PRODUCTION_CHATBOT_GUIDE.md](./PRODUCTION_CHATBOT_GUIDE.md)** - Complete feature guide
- **[example_python_client.py](./example_python_client.py)** - Python usage examples
- **[example_javascript_client.js](./example_javascript_client.js)** - JavaScript usage examples
- **[CLAUDE.md](./CLAUDE.md)** - Architecture overview

---

## 🎯 Next Steps

1. **Test the API** - Run the quick start examples above
2. **Upload Documents** - Add your company documents via `/api/v1/upload`
3. **Customize System Prompt** - Edit `BASE_SYSTEM_PROMPT` in `llm_generator.py`
4. **Deploy** - Use Docker Compose for production
5. **Monitor** - Track latencies and cache hit rates

---

## 📞 Support

- Check logs: `docker compose logs -f app`
- API docs: `http://localhost:8081/docs` (Swagger)
- Health: `http://localhost:8081/v1/health`

---

**Status:** ✅ Production Ready  
**Version:** 1.0.0  
**Last Updated:** May 11, 2026  

Happy chatting! 🎉
