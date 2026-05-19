# Nexo Chatbot

A high-performance, generic website chatbot with hybrid intelligence — combining Retrieval-Augmented Generation (RAG), real-time web search, and Google Gemini AI. Built with FastAPI, Qdrant, Redis, and MongoDB. Drop it in front of any website to give it an intelligent chat interface.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [WebSocket Protocol](#websocket-protocol)
- [MongoDB Schema](#mongodb-schema)
- [Docker Setup](#docker-setup)
- [Technical Details](#technical-details)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
User Request  { query, session_id, stream }
    │
    ├── POST /api/v1/chat           ──► Intent Classifier (Gemini)
    │                                       │
    │                              ┌────────┼──────────┐
    │                           domain      web      general
    │                              │         │          │
    │                         Vector DB   Gemini     (none)
    │                          + Rerank    Search
    │                         → Web fallback
    │                              │         │          │
    │                              └─────────┴──────────┘
    │                                       │
    │                 Conversation history fetched server-side (MongoDB)
    │                                       │
    │                          Gemini LLM (retry on 429)
    │                                       │
    │                     Redis Cache + MongoDB (encrypted)
    │                                       │
    │              ChatResponse { answer, intent, sources, token_usage }
    │
    └── WS  /v1/ws/web_chat/{session_id}
              Client → {"question": "...", "query_time": "..."}
              Server → {"status":"connected"}
                     → {"type":"status",   "message":"processing"}
                     → {"type":"stream",   "token":"..."}      (per chunk)
                     → {"type":"final",    "message":"...", "answer_time":"..."}
                     → {"type":"cancelled","message":"..."}
                     → {"type":"error",    "message":"..."}
```

### Component Map

| Layer | Technology | Purpose |
|---|---|---|
| API Gateway | FastAPI (port 8081) | HTTP + WebSocket endpoints |
| LLM | Google Gemini `gemini-2.0-flash` | Intent classification, generation, web search |
| Vector DB | Qdrant | Hybrid semantic + keyword search |
| Cache | Redis | Response cache (1 hr), doc cache (10 min) |
| Document DB | MongoDB | Encrypted chat history |
| Embeddings | Gemini `gemini-embedding-001` / `all-MiniLM-L6-v2` | Query and document embeddings |
| Web Search | Gemini built-in Google Search grounding | Real-time search (no external API needed) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) | Secure storage of all queries/responses |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 recommended |
| Docker + Docker Compose | 24+ | For infrastructure services |
| Google Gemini API Key | — | [Get key](https://aistudio.google.com/app/apikey) |
| MongoDB | 7.0+ | Via Docker or Atlas |
| Redis | 7.x | Via Docker |
| Qdrant | 1.11+ | Via Docker |

> No OpenAI key or external search API key required. Gemini handles embeddings and web search natively.

---

## Quickstart

### 1. Clone and enter the project

```bash
git clone <repo-url> nexo-chatbot
cd nexo-chatbot
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt

# Optional: install Playwright browser for JavaScript-heavy (SPA) website scraping
playwright install chromium
```

### 4. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
GEMINI_API_KEY=AIza<your-key>
ENCRYPTION_KEY=<any-strong-random-string>
```

### 5. Start infrastructure services

```bash
docker compose up qdrant redis mongodb -d
```

Verify they are running:

```bash
docker compose ps
```

### 6. Run the application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

API available at `http://localhost:8081`. Interactive docs: `http://localhost:8081/docs`

### 7. Ingest a domain website (optional but recommended)

```bash
curl -X POST http://localhost:8081/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://your-domain.com"], "site_name": "my_domain"}'
```

The scraper crawls all pages including SPAs (hash routes like `/#/about`), follows every link, and discovers URLs from `sitemap.xml` and `robots.txt`.

### 8. Test the endpoints

**Domain query:**
```bash
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is your refund policy?", "session_id": "user-001"}'
```

**Web search query:**
```bash
curl -X POST http://localhost:8081/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest AI news?", "session_id": "user-001"}'
```

**WebSocket (using wscat):**
```bash
npm install -g wscat
wscat -c ws://localhost:8081/ws/web_chat/session-001
# then type JSON: {"question": "Tell me about your services"}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes* | — | Google Gemini API key (`*` unless Vertex AI) |
| `USE_VERTEX_AI` | No | `false` | Use Vertex AI instead of Gemini API |
| `VERTEX_PROJECT` | Yes* | — | GCP project ID (`*` when `USE_VERTEX_AI=true`) |
| `VERTEX_LOCATION` | No | `us-central1` | GCP region for Vertex AI |
| `LLM_MODEL` | No | `gemini-2.0-flash` | Gemini model name |
| `LLM_MAX_TOKENS` | No | `2048` | Max output tokens per LLM response |
| `LLM_TEMPERATURE` | No | `0.1` | LLM sampling temperature |
| `LLM_MAX_RETRIES` | No | `3` | Retry attempts on 429 quota errors |
| `MONGODB_URL` | No | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DB` | No | `nexo_chatbot` | MongoDB database name |
| `ENCRYPTION_KEY` | Yes | — | Secret key for Fernet encryption of stored data |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |
| `CACHE_TTL_SECONDS` | No | `3600` | Response cache TTL (seconds) |
| `QDRANT_HOST` | No | `localhost` | Qdrant host |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `QDRANT_COLLECTION` | No | `domain_docs` | Qdrant collection name |
| `EMBEDDING_MODEL` | No | `models/gemini-embedding-001` | Gemini embedding model |
| `EMBEDDING_DIM` | No | `3072` | Embedding dimension (set `384` for local fallback) |
| `TOP_K` | No | `5` | Documents retrieved from vector DB |
| `SIMILARITY_THRESHOLD` | No | `0.65` | Min score before web search fallback |
| `RERANK_TOP_N` | No | `3` | Chunks kept after reranking |
| `CHUNK_SIZE` | No | `512` | Ingestion chunk size (tokens) |
| `CHUNK_OVERLAP` | No | `75` | Ingestion chunk overlap (tokens) |
| `MAX_PAGES_PER_DOMAIN` | No | `100` | Max pages per ingestion job |
| `WS_TIMEOUT_SECONDS` | No | `120` | WebSocket inactivity auto-close timeout |

---

## API Reference

### Active Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Service health check |
| `GET` | `/version` | Get API version |
| `POST` | `/api/v1/chat` | Unified chat (all intents, non-streaming) |
| `POST` | `/api/v1/chat/stream` | Streaming chat via SSE |
| `POST` | `/api/v1/ingest` | Scrape and index a website |
| `POST` | `/api/v1/upload` | Upload and process files |
| `WS` | `/v1/ws/web_chat/{session_id}` | Real-time streaming over WebSocket |

---

### `GET /v1/health`

Returns service health status.

**Response:**
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

> `status` is `"healthy"` when all components are reachable, `"degraded"` otherwise. Individual component values are `"ok"` or `"unavailable"`.

---

### `GET /version`

Returns the current API version.

**Response:**
```json
{
  "version": "1.0.0"
}
```

---

### `POST /api/v1/chat`

Unified chat endpoint. Routes queries through intent classification — domain, web search, or general — in a single call.

> Sending `"stream": true` to this endpoint returns HTTP 400. Use `POST /api/v1/chat/stream` for streaming.

**Request:**
```json
{
  "query": "What is your return policy?",
  "session_id": "user-123",
  "stream": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string (1–2000 chars) | Yes | The user's question |
| `session_id` | string | No | Used to fetch conversation history server-side from MongoDB |
| `stream` | bool | No | Must be `false` (default). Use `/chat/stream` for SSE. |

> `session_id` enables multi-turn conversation. History is fetched and decrypted server-side — the client never sends history.

**Response:**
```json
{
  "answer": "Our return policy allows returns within 30 days...",
  "intent": "domain",
  "sources": [
    {"title": "my_domain", "url": "https://example.com/policy", "snippet": null}
  ],
  "confidence": 0.91,
  "latency_ms": 843.2,
  "cached": false,
  "token_usage": {
    "input_tokens": 412,
    "output_tokens": 87,
    "thoughts_tokens": 0,
    "total_tokens": 499
  }
}
```

| Response Field | Type | Description |
|---|---|---|
| `answer` | string | Generated response text |
| `intent` | string | Classified intent: `domain`, `web`, or `general` |
| `sources` | array | Citations from RAG or Google Search grounding |
| `confidence` | float | Intent classifier confidence (0–1) |
| `latency_ms` | float | End-to-end request latency |
| `cached` | bool | `true` if response was served from Redis cache |
| `token_usage` | object | LLM token counts (`input`, `output`, `thoughts`, `total`) |

---

### `POST /api/v1/chat/stream`

Streaming chat via Server-Sent Events (SSE). Accepts the same request body as `POST /api/v1/chat`.

**Request:** Same as `/api/v1/chat` above.

**Response:** `Content-Type: text/event-stream`

```
data: Our return

data:  policy allows

data:  returns within

data:  30 days...

data: [DONE]
```

Each `data:` line is a text chunk (LLM token or word). The stream ends with `data: [DONE]`. On error, `data: [ERROR] <detail>` is emitted.

---

### `POST /api/v1/ingest`

Scrape one or more websites and index the content into Qdrant for domain retrieval.

**Request:**
```json
{
  "urls": ["https://example.com"],
  "site_name": "example_site",
  "force_refresh": false
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array of strings | Yes | Seed URLs to crawl |
| `site_name` | string | Yes | Label stored with each indexed chunk |
| `force_refresh` | bool | No | Re-index even if already indexed (default `false`) |

**Response:**
```json
{
  "status": "success",
  "pages_scraped": 14,
  "chunks_indexed": 187,
  "errors": []
}
```

The scraper crawls all linked pages, follows `sitemap.xml` and `robots.txt`, and supports JavaScript-rendered SPAs (hash routes) when Playwright is installed.

---

## WebSocket Protocol

**Endpoint:** `ws://localhost:8081/v1/ws/web_chat/{session_id}`

### Message formats

**Client → Server (JSON):**
```json
{"question": "What are your business hours?", "query_time": "2026-03-18T12:00:00Z"}
```

**Server → Client:**

| Type | When | Payload |
|---|---|---|
| `{"status":"connected"}` | On connect | Connection confirmation |
| `{"type":"status","message":"processing"}` | Before generation | Processing acknowledgement |
| `{"type":"stream","token":"..."}` | During generation | Streamed text chunk |
| `{"type":"final",...}` | After generation | Full result |
| `{"type":"cancelled","message":"...","answer_time":"..."}` | On cancel | Partial response |
| `{"type":"error","message":"..."}` | On failure | Error detail |

### Final message structure

```json
{
  "type":          "final",
  "message":       "<full response text>",
  "answer_time":   "2026-03-18 12:38:28.394862+00:00",
  "input_tokens":  347,
  "output_tokens": 229
}
```

### Connection flow

```
Client                                  Server
  │── connect ────────────────────────► │
  │                                     │◄── {"status":"connected"}
  │
  │── {"question":"What are your        │
  │    business hours?"}  ────────────► │
  │                                     │◄── {"type":"status","message":"processing"}
  │                                     │◄── {"type":"stream","token":"Our "}
  │                                     │◄── {"type":"stream","token":"business "}
  │                                     │    ... (all tokens) ...
  │                                     │◄── {"type":"final", "message":"..."}
  │
  │── (idle > 120s) ───────────────────►│◄── {"type":"error","message":"timed out"}
  │                                     │    (connection closed)
```

### Auto-timeout

Connections are automatically closed after `WS_TIMEOUT_SECONDS` (default 120s) of inactivity. The timer resets on each received message.

---

## MongoDB Schema

### `chat_history`

All queries and responses are stored encrypted. Fetched server-side by `session_id` to build conversation history for the LLM.

```json
{
  "session_id":  "user-123",
  "query":       "<fernet-encrypted string>",
  "response":    "<fernet-encrypted string>",
  "token_usage": {"input_tokens": 412, "output_tokens": 87, "total_tokens": 499},
  "timestamp":   "2026-03-18T10:23:00Z"
}
```

---

## Docker Setup

### Start all services

```bash
docker compose up -d
```

### Start only infrastructure (run app locally)

```bash
docker compose up qdrant redis mongodb -d
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

### View logs

```bash
docker compose logs -f app
```

### Stop everything

```bash
docker compose down
```

### Reset all data volumes

```bash
docker compose down -v
```

---

## Technical Details

### Intent Classification

Each query is classified by Gemini into one of three intents:

| Intent | Trigger | Action |
|---|---|---|
| `domain` | Product-specific, policy, procedural | Qdrant vector search → Gemini Search fallback |
| `web` | Current events, live data, recent news | Gemini Google Search grounding |
| `general` | Definitions, history, math, coding | LLM direct (no retrieval) |

Classification returns structured JSON: `intent`, `confidence` (0–1), and `rewritten_query`. On LLM failure, a keyword-heuristic fallback is used.

### Conversation History

History is managed **entirely server-side**. The frontend only sends `session_id`. The server:

1. Fetches the last 6 turns from `chat_history` for that session
2. Decrypts them using `ENCRYPTION_KEY`
3. Injects as `types.Content` history into the Gemini chat context

### Hybrid Retrieval

```
fused_score = (semantic_score × 0.7) + (keyword_overlap × 0.3)
```

Improves precision for short queries without requiring a separate BM25 index.

### Cross-Encoder Reranking

Retrieved chunks are reranked with `cross-encoder/ms-marco-MiniLM-L-6-v2`. Loaded lazily on first use. Falls back to score-based ordering if unavailable.

### Embeddings

| Backend | Model | Dimensions | When used |
|---|---|---|---|
| Gemini API | `models/gemini-embedding-001` | 3072 | `GEMINI_API_KEY` is set |
| Local | `all-MiniLM-L6-v2` | 384 | No API key / Gemini failure |

If you switch backends, delete the Qdrant collection and restart (it recreates with the correct dimension).

### Gemini Retry Logic

Exponential back-off on HTTP 429 quota errors:

| Attempt | Wait |
|---|---|
| 1 | immediate |
| 2 | 1 second |
| 3 | 2 seconds |
| 4 | 4 seconds |

Controlled by `LLM_MAX_RETRIES` (default `3`).

### Grounding Citations

Gemini grounding sources are extracted from two response locations:

1. `grounding_chunks[].web` — standard (title + URI)
2. `search_entry_point.rendered_content` — HTML chip fallback (parsed when `grounding_chunks` is `None`)

### Encryption

Stored queries and responses use **Fernet** (AES-128-CBC + HMAC-SHA256). `ENCRYPTION_KEY` is SHA-256 hashed to produce a deterministic 32-byte key. Decrypt stored values with `app.utils.encryption.decrypt(token, key)`.

### Caching Strategy

| Cache | Backend | TTL | Key |
|---|---|---|---|
| Full responses | Redis | 1 hour | SHA-256(query) |
| Retrieved docs | Redis | 10 min | SHA-256(query) |

---

## Troubleshooting

### `Connection refused` on startup

```bash
docker compose ps   # all services should show "Up"
```

### `GEMINI_API_KEY not set`

Copy `.env.example` to `.env` and fill in your key.

### `EMBEDDING_DIM mismatch` in Qdrant

```bash
curl -X DELETE http://localhost:6333/collections/domain_docs
# Restart the app — it recreates the collection with the correct dimension
```

### `pages_scraped: N, chunks_indexed: 0`

JavaScript-rendered site — Playwright is needed:

```bash
playwright install chromium
```

### WebSocket connection drops immediately

Check `WS_TIMEOUT_SECONDS`. Default is 120 seconds of inactivity.

### 429 Quota errors persisting

Increase `LLM_MAX_RETRIES` or switch to `gemini-2.0-flash-lite`.
