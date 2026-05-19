# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

Two separate codebases that work together:

- **Backend:** `c:\Users\S KISHORE\Downloads\nexo-chatbot-29-04-2026 - changes\nexo-chatbot-29-04-2026 - changes\` — FastAPI RAG API
- **Frontend:** `C:\Users\S KISHORE\Downloads\chatbot_ui_08\chatbot_ui_08\` — React/Vite chatbot UI

---

## Commands

### Backend (FastAPI)

```powershell
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium  # for JS-rendered site scraping

# Run dev server (port 8081)
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload

# Run with Docker (starts Qdrant, Redis, MongoDB + app)
docker compose up -d
docker compose ps
docker compose logs -f app
```

### Frontend (chatbot_ui_08)

```powershell
cd "C:\Users\S KISHORE\Downloads\chatbot_ui_08\chatbot_ui_08"

npm install
npm run dev          # Vite dev server on port 3000
npm run build        # Production build → dist/
npm run build:widget # Widget IIFE build (chatbot.iife.js)
npm run lint         # ESLint
npm run server       # Express proxy server
```

### Local Services (Windows, no Docker)

```powershell
net start MongoDB
D:\Nexo\services\redis\redis-server.exe
D:\Nexo\services\qdrant\qdrant.exe
```

---

## Architecture

### Request Flow

Both the web UI and WhatsApp are input channels that funnel into the same orchestrator:

```
┌─────────────────────┐        ┌──────────────────────────┐
│  Web User (Browser) │        │  WhatsApp User            │
│  React UI :3000     │        │  (Meta Cloud API webhook) │
└────────┬────────────┘        └────────────┬─────────────┘
         │ HTTP/WebSocket                   │ POST /api/v1/whatsapp/webhook
         │ (session_id = UUID)              │ (session_id = phone number E.164)
         └──────────────┬───────────────────┘
                        ▼
              FastAPI Backend :8081
                        │
                        ▼
              Intent Classification (Gemini)
                ├─ domain  → Qdrant vector search → rerank → Gemini generation
                ├─ web     → Gemini Google Search grounding
                └─ general → Direct Gemini LLM
                        │
                        ▼
              Encrypt + store in MongoDB   (keyed by session_id)
              Cache in Redis (1 hr TTL)
                        │
                 ┌──────┴──────┐
                 ▼             ▼
          HTTP/WS reply    WhatsApp Cloud API
          to web client    POST reply to sender
```

**Session identity across channels:**
- Web users: `session_id` is a browser-generated UUID (persisted in `localStorage`)
- WhatsApp users: `session_id` is the sender's E.164 phone number (e.g. `+919876543210`)
- Both share the same MongoDB history collection — a user can optionally link their web session to their phone number to get cross-channel history continuity

### Backend: Key Modules

| Path | Role |
|------|------|
| `app/main.py` | FastAPI app init, lifespan (startup/shutdown of all services) |
| `app/config/settings.py` | All config via Pydantic Settings (reads `.env`) |
| `app/services/orchestrator.py` | Single entry point — routes query to domain/web/general handler |
| `app/services/intent_classifier.py` | Classifies query intent using Gemini |
| `app/services/llm_generator.py` | Gemini inference + streaming (retries on 429) |
| `app/retrieval/vector_store.py` | Qdrant async client (hybrid search) |
| `app/retrieval/reranker.py` | Cross-encoder reranking of retrieved chunks |
| `app/ingestion/pipeline.py` | Full ETL: scrape → clean → chunk → embed → upsert |
| `app/services/mongodb.py` | Encrypted chat history (async, motor) |
| `app/services/cache.py` | Redis response cache |
| `app/utils/encryption.py` | Fernet encryption for all stored queries/responses |
| `app/api/routes/websocket_chat.py` | WebSocket endpoint (`/v1/ws/web_chat/{session_id}`) |

### Frontend: Key Components

| File | Role |
|------|------|
| `src/components/ChatContainer.jsx` | All chat state, WebSocket connection, streaming, speech-to-text |
| `src/components/MessageBubble.jsx` | Message display with streaming cursor + typing indicator |
| `src/widget-entry.jsx` | Embeddable widget entry (IIFE build) with `window.ChatBot` API |
| `src/App.jsx` | Sets `apiBaseUrl` (Azure deployment URL) |
| `vite.config.js` | Proxies `/ws` → `ws://localhost:8000`, `/api` → `http://localhost:8000` |

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/chat` | Non-streaming chat |
| `POST` | `/api/v1/chat/stream` | SSE streaming chat |
| `WS` | `/v1/ws/web_chat/{session_id}` | Real-time WebSocket |
| `POST` | `/api/v1/ingest` | Scrape website + index into Qdrant |
| `POST` | `/api/v1/upload` | Upload files (PDF/DOCX/XLSX/PPTX) for indexing |
| `GET` | `/v1/health` | Redis, MongoDB, Qdrant status |

### WhatsApp Business API Endpoints (to be built)

These endpoints need to be added under `app/api/routes/whatsapp.py` and registered in `app/main.py`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/whatsapp/webhook` | Meta webhook verification (challenge-response handshake) |
| `POST` | `/api/v1/whatsapp/webhook` | Receive incoming WhatsApp messages and events from Meta |
| `POST` | `/api/v1/whatsapp/send` | Send a WhatsApp message to a phone number (outbound) |

**Webhook verification flow (`GET /api/v1/whatsapp/webhook`):**

Meta sends three query params: `hub.mode`, `hub.verify_token`, and `hub.challenge`. The handler must verify that `hub.mode == "subscribe"` and `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN` from `.env`, then return `hub.challenge` as a plain-text `200` response.

**Incoming message flow (`POST /api/v1/whatsapp/webhook`):**

1. Meta POSTs a JSON payload containing `entry[].changes[].value.messages[]`
2. Extract `from` (sender phone number), `id` (message ID), and `text.body` (message text)
3. Always respond `200 OK` immediately (Meta retries if it doesn't get 200 within 20 s)
4. Forward the message text to the orchestrator (`app/services/orchestrator.py`) using the sender's phone number as `session_id`
5. Send the generated reply back via the WhatsApp Cloud API (`POST https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`)

**Required `.env` variables for WhatsApp:**

| Variable | Purpose |
|----------|---------|
| `WHATSAPP_VERIFY_TOKEN` | Secret token used to verify Meta's webhook subscription |
| `WHATSAPP_ACCESS_TOKEN` | Meta permanent system-user access token for sending messages |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone Number ID from the Meta App Dashboard |

**Outbound message payload to Meta Cloud API:**

```json
{
  "messaging_product": "whatsapp",
  "to": "<recipient_phone_e164>",
  "type": "text",
  "text": { "body": "<response_text>" }
}
```

**Suggested module layout:**

```
app/api/routes/whatsapp.py   # GET + POST /api/v1/whatsapp/webhook, POST /api/v1/whatsapp/send
app/services/whatsapp.py     # WhatsApp Cloud API client (send_message, parse_inbound)
```

Register in `app/main.py`:
```python
from app.api.routes.whatsapp import router as whatsapp_router
app.include_router(whatsapp_router)
```

#### Web → WhatsApp handoff (for web users who want to continue on WhatsApp)

Web users can be offered a **"Chat on WhatsApp"** deep-link button in the React UI that pre-fills the conversation context:

```
https://wa.me/<WHATSAPP_PHONE_NUMBER>?text=<url-encoded greeting>
```

- `WHATSAPP_PHONE_NUMBER` is the business phone number exposed as a frontend env var (`VITE_WHATSAPP_NUMBER`)
- The link opens WhatsApp (mobile app or web.whatsapp.com) and puts the user in a chat with the bot
- Once the user sends the first message via WhatsApp, the webhook flow takes over and the bot replies there

**Session linking (optional):** To give a WhatsApp user access to their web conversation history, add a `POST /api/v1/whatsapp/link-session` endpoint that accepts `{ web_session_id, phone_number }` and stores the mapping in MongoDB. The orchestrator can then merge history from both session IDs when generating replies.

---

## Key Design Decisions

- **Async-first:** All services use async clients (motor, qdrant_client async, aioredis).
- **Server-side history:** Chat history is fetched from MongoDB server-side using `session_id`; the client only sends the current query.
- **Encryption at rest:** All stored queries and responses are Fernet-encrypted (`app/utils/encryption.py`). The key is in `.env` as `ENCRYPTION_KEY`.
- **Graceful degradation:** Cache miss, MongoDB failure, or Qdrant unavailability are handled independently — the chat still functions.
- **Widget build:** `npm run build:widget` produces a single `chatbot.iife.js` + CSS that can be dropped into any webpage via `<script>` tag. The widget is configured via `window.ChatBot.init({ apiUrl, wsUrl, mock, targetId })`.
- **Background uploads:** File uploads go through RQ (Redis Queue) for async processing via `app/services/queue.py` + `app/services/upload_tasks.py`.
- **Intent routing thresholds:** Domain intent triggers at ≥0.60 confidence; similarity threshold for retrieval is 0.65 (falls back to 0.3 if no results).

---

## Environment Variables (`.env`)

Key variables in `app/config/settings.py`:

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini API (intent, generation, embeddings, web search) |
| `LLM_MODEL` | Model name (e.g. `gemini-2.5-flash`) |
| `MONGODB_URL` | MongoDB Atlas or local connection string |
| `ENCRYPTION_KEY` | Fernet key for chat history encryption |
| `REDIS_URL` | Redis connection (default: `redis://localhost:6379`) |
| `QDRANT_HOST` / `QDRANT_API_KEY` | Qdrant vector DB (cloud or local) |
| `TOP_K` | Number of chunks to retrieve (default: 5) |
| `SIMILARITY_THRESHOLD` | Min score for domain retrieval (default: 0.65) |
