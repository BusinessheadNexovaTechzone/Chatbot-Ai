# Chat Endpoint Documentation

## Overview
The chat endpoint is the main interface for querying the Nexo Chatbot system. It intelligently routes queries to retrieve relevant data from uploaded documents and generates contextual answers.

## Request/Response Flow

### Request Format
```json
{
  "query": "who is the ceo",
  "session_id": "string (optional)",
  "stream": false,
  "assistant_name": "Assistant"
}
```

### Response Format
```json
{
  "answer": "Leadership The company is led by Arjun Mehrotra, Chief Executive Officer...",
  "assistant_name": "Assistant",
  "intent": "domain",
  "sources": [
    {
      "title": "uploaded_file",
      "url": "NexaVault_Company_Profile.pdf",
      "snippet": "Leadership The company is led by Arjun Mehrotra..."
    }
  ],
  "confidence": 0.6,
  "latency_ms": 45486.66,
  "cached": false,
  "token_usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "thoughts_tokens": 0,
    "total_tokens": 0
  }
}
```

## How It Works

### 1. **Intent Classification**
The system classifies incoming queries into three categories:

#### **DOMAIN Intent**
- Queries about company-specific information found in uploaded documents
- Examples: "who is the ceo", "what are your services", "company headquarters"
- **Strategy**: Retrieves relevant chunks from vector database

#### **WEB Intent**
- Queries requiring current, real-time information
- Examples: "what's the latest news", "current stock price", "today's weather"
- **Strategy**: Uses web search for grounding

#### **GENERAL Intent**
- Queries about general knowledge, math, coding, definitions
- Examples: "explain machine learning", "what is encryption", "how to solve quadratic equations"
- **Strategy**: Direct LLM response without external retrieval

### 2. **Query Routing Logic**

```
User Query
    ↓
Intent Classification
    ↓
    ├─→ DOMAIN → Vector Search → Retrieve Chunks → LLM Generation → Answer
    ├─→ WEB → Web Search → Web Results → LLM Generation → Answer
    └─→ GENERAL → Direct LLM → Answer
```

### 3. **Domain Query Processing** (for "who is the ceo")

**Step 1: Query Classification**
- Query: "who is the ceo"
- Detected Intent: **DOMAIN** (identified by keyword "who" in short query)
- Confidence: 0.6

**Step 2: Vector Search**
- Query is embedded and searched against uploaded document vectors
- Top matching chunks are retrieved from the vector database
- Chunks are scored by semantic similarity

**Step 3: Chunk Filtering**
- Chunks are filtered for specific sections (e.g., "leadership", "ceo")
- The system prioritizes chunks most relevant to the query
- Returns filtered chunks with highest relevance

**Step 4: LLM Generation**
- Retrieved chunks are formatted as context
- LLM generates answer based on document content
- Response includes citations pointing to source documents

**Step 5: Response**
- Answer: Leadership information from the document
- Sources: File name and URL of the source document
- Confidence: Based on vector similarity scores

### 4. **Fallback Logic**

If the LLM fails (e.g., API error), the system:
1. Checks if domain chunks were retrieved
2. If yes: Returns the raw chunk content as the answer
3. If no: Returns a friendly error message

This ensures users always get some useful information even when services are temporarily unavailable.

## Key Features

### ✅ Document-Aware Responses
- Queries about uploaded documents automatically retrieve relevant information
- Example answers include citations pointing to source files
- Content is properly cleaned and formatted

### ✅ Intelligent Intent Detection
- Heuristic-based fallback when LLM is unavailable
- Detects question words ("who", "what", "where") in queries
- Routes queries appropriately based on content

### ✅ Semantic Filtering
For specific queries, the system applies section-based filtering:
- "who is the ceo" → searches for "leadership" section
- "where is headquarters" → searches for "headquarters" section
- "what services" → searches for "core services" section

### ✅ Resilient Design
- Graceful fallback when LLM is unavailable
- Caching support for repeated queries
- MongoDB integration for conversation history

### ✅ Source Attribution
- Every answer includes sources
- Citations show document name and snippet preview
- Users can trace answers back to original documents

## Example: "Who is the CEO"

### Request
```bash
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "who is the ceo",
    "session_id": "user_123",
    "stream": false,
    "assistant_name": "Assistant"
  }'
```

### Response
```json
{
  "answer": "Leadership The company is led by Arjun Mehrotra, Chief Executive Officer, who brings over 20 years of experience in enterprise IT and cybersecurity...",
  "assistant_name": "Assistant",
  "intent": "domain",
  "sources": [
    {
      "title": "uploaded_file",
      "url": "NexaVault_Company_Profile.pdf",
      "snippet": "Leadership The company is led by Arjun Mehrotra..."
    }
  ],
  "confidence": 0.6,
  "latency_ms": 45486.66,
  "cached": false
}
```

## Configuration

### Settings (.env)
```
# Model Configuration
LLM_MODEL=gemini-1.5-pro
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.1
LLM_MAX_RETRIES=3

# Vector Database
QDRANT_HOST=https://57a54363-216f-486b-a8c8-79fb68e26c51.eu-central-1-0.aws.cloud.qdrant.io
QDRANT_API_KEY=eyJhbGci...

# Retrieval Parameters
TOP_K=5
SIMILARITY_THRESHOLD=0.65

# Embedding
EMBEDDING_DIM=3072
```

### Section Mappings (orchestrator.py)
The system recognizes specific keywords and maps them to document sections:

```python
section_mappings = {
    'ceo': ['leadership'],
    'headquarters': ['headquarters'],
    'location': ['headquarters'],
    'services': ['core services'],
    'awards': ['achievements and recognition'],
}
```

## API Endpoints

### Main Chat Endpoint
```
POST /api/v1/chat
Content-Type: application/json

Request:
{
  "query": "your question",
  "session_id": "optional_session_id",
  "stream": false,
  "assistant_name": "Assistant"
}

Response: ChatResponse
```

### Streaming Chat Endpoint
```
POST /api/v1/chat/stream
Content-Type: application/json

Request:
{
  "query": "your question",
  "session_id": "optional_session_id",
  "stream": true,
  "assistant_name": "Assistant"
}

Response: Server-Sent Events (streaming text chunks)
```

## Supported Document Types

- **PDF** (.pdf)
- **Word** (.docx, .doc)
- **Excel** (.xlsx, .xls)
- **PowerPoint** (.pptx)
- **Text** (.txt)
- **Markdown** (.md)

Documents are automatically extracted, chunked, embedded, and indexed into the vector database.

## Troubleshooting

### Issue: Getting generic fallback response
**Cause**: LLM service is unavailable or documents not uploaded

**Solution**:
1. Check LLM_MODEL in .env is correct
2. Ensure documents are uploaded via `/api/v1/upload`
3. Verify vector database connectivity
4. Check Gemini API key validity

### Issue: Sources not appearing
**Cause**: Document chunks not properly indexed

**Solution**:
1. Re-upload the document using the upload endpoint
2. Verify Qdrant connection
3. Check chunk content length (minimum recommended 100 chars)

### Issue: Low confidence scores
**Cause**: Query doesn't match document content well

**Solution**:
1. Try rephrasing the query
2. Use keywords from the document
3. Upload more relevant documents
4. Adjust SIMILARITY_THRESHOLD in .env

## Performance Metrics

- **Average Latency**: 30-50 seconds (includes MongoDB and embedding delays)
- **Cache Hit**: ~5-10 seconds when result is cached
- **Vector Search**: 1-2 seconds
- **LLM Generation**: 15-30 seconds
- **Document Retrieval**: 1-3 seconds

## Security Considerations

- Queries are encrypted before storage in MongoDB (ENCRYPTION_KEY in .env)
- Responses are cached in Redis
- Document content is not exposed in logs
- API Key for Gemini is required (.env file)

## Best Practices

1. **Upload Business Documents**: Upload company profiles, product docs, procedures
2. **Use Specific Queries**: "Who is the CEO" works better than "Tell me about the company"
3. **Monitor Latency**: Adjust LLM_MAX_TOKENS if latency is too high
4. **Regular Cache Clearing**: Use `/health` endpoint to check system status
5. **Session Management**: Use session_id to maintain conversation context

## Future Enhancements

- [ ] Multi-turn conversations with context awareness
- [ ] Document chunking strategy customization
- [ ] Custom section mapping per document
- [ ] Multi-language support
- [ ] Document version control
- [ ] Advanced filtering and faceted search
- [ ] Confidence threshold customization per query type
