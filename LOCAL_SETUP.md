# Nexo Chatbot — Local Setup (No Docker)

---

## Services at a Glance

| Service  | Port        | Location |
|----------|-------------|----------|
| MongoDB  | 27017       | Windows Service |
| Redis    | 6379        | `D:\Nexo\services\redis\redis-server.exe` |
| Qdrant   | 6333 / 6334 | `D:\Nexo\services\qdrant\qdrant.exe` |
| FastAPI  | **8082**    | `D:\Nexo\nexo-chatbot\.venv` |
| Frontend | 3000        | `D:\Nexo\chatbot-app` (React + Vite) |

> **Note on port 8081:** If port 8081 is occupied by a ghost process (common on Windows after an unclean shutdown), use **8082** and update `chatbot-app\vite.config.js` proxy targets to match. After a system reboot, 8081 will be free again.

---

## One-Time Setup

### 1. MongoDB (Windows Service)

```powershell
sc query MongoDB
# If not RUNNING:
net start MongoDB
```

### 2. Python virtual environment

```powershell
cd D:\Nexo\nexo-chatbot
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3. Install Playwright browser (for JS-rendered sites)

```powershell
.venv\Scripts\playwright install chromium
```

### 4. Configure environment

```powershell
copy .env.example .env
```

Edit `.env` — minimum required keys:

```env
GEMINI_API_KEY=AIza<your-key>
ENCRYPTION_KEY=<any-strong-random-string-32-chars>
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB=nexo_chatbot
REDIS_URL=redis://localhost:6379
QDRANT_HOST=localhost
QDRANT_PORT=6333
LLM_MODEL=gemini-2.5-flash
```

### 5. Frontend dependencies

```powershell
cd D:\Nexo\chatbot-app
npm install
```

---

## Quickstart (Every Session)

Open **4 terminal windows** (Windows Terminal tabs recommended):

### Terminal 1 — Redis

```powershell
D:\Nexo\services\redis\redis-server.exe D:\Nexo\services\redis\redis.windows.conf
```

Verify: `D:\Nexo\services\redis\redis-cli.exe ping` → `PONG`

---

### Terminal 2 — Qdrant

```powershell
D:\Nexo\services\qdrant\qdrant.exe
```

Verify: `curl http://localhost:6333/healthz` → `healthz check passed`
Dashboard: `http://localhost:6333/dashboard`

---

### Terminal 3 — FastAPI Backend

```powershell
cd D:\Nexo\nexo-chatbot
.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8082
```

Verify:
```powershell
Invoke-WebRequest -Uri http://localhost:8082/health | Select-Object -ExpandProperty Content
```

Expected:
```json
{"status":"healthy","version":"1.0.0","components":{"redis":"ok","mongodb":"ok","qdrant":"ok"}}
```

API docs: `http://localhost:8082/docs`

---

### Terminal 4 — Frontend

```powershell
cd D:\Nexo\chatbot-app
npm run dev
```

Open: `http://localhost:3000`

---

## Ingesting a Website

After the backend is running, POST to `/api/v1/ingest` with the target site.

### PowerShell

```powershell
Invoke-WebRequest -Uri "http://localhost:8082/api/v1/ingest" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"site_name": "Nexova", "urls": ["https://nexovaglobaltechnology.com/"], "force_refresh": false}'
```

### Git Bash / WSL

```bash
curl -X POST http://localhost:8082/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"site_name": "Nexova", "urls": ["https://nexovaglobaltechnology.com/"], "force_refresh": false}'
```

### Swagger UI (no command needed)

Open `http://localhost:8082/docs` → `POST /api/v1/ingest` → **Try it out** → paste body → **Execute**.

### Request body

```json
{
  "site_name": "Nexova",
  "urls": ["https://nexovaglobaltechnology.com/"],
  "force_refresh": false
}
```

| Field | Description |
|-------|-------------|
| `site_name` | Label shown in citations when the bot answers from this site |
| `urls` | One or more seed URLs — the scraper auto-discovers the full domain via sitemap + BFS crawl |
| `force_refresh` | Reserved (unused) — re-ingestion always upserts safely |

### Expected response

```json
{
  "status": "success",
  "pages_scraped": 24,
  "chunks_indexed": 143,
  "errors": []
}
```

### What happens under the hood

```
URL seeds → sitemap.xml discovery → BFS link crawl
  → Playwright (headless Chromium) renders each page
  → Text cleaned + split into chunks
  → Gemini embeddings generated
  → Chunks upserted into Qdrant
```

After ingestion, asking the chatbot anything about that website will route to **domain** intent and answer from the indexed content.

---

## Testing the Full Flow

### 1. Ask a domain question (after ingestion)

```powershell
Invoke-WebRequest -Uri "http://localhost:8082/api/v1/chat" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"query": "What services does Nexova offer?", "session_id": "test-001"}'
```

### 2. WebSocket chat (multi-turn, streaming)

Install wscat once: `npm install -g wscat`

```bash
wscat -c ws://localhost:8082/ws/web_chat/my-session-id
# then type:
{"question": "What does Nexova do?"}
```

Or just open `http://localhost:3000` — the frontend uses WebSocket automatically.

---

## Stopping Everything

| Service  | How to stop |
|----------|-------------|
| Redis    | `Ctrl+C` in Terminal 1 |
| Qdrant   | `Ctrl+C` in Terminal 2 |
| FastAPI  | `Ctrl+C` in Terminal 3 |
| Frontend | `Ctrl+C` in Terminal 4 |
| MongoDB  | `net stop MongoDB` (optional — it's a Windows service) |

---

## Troubleshooting

### Port 8082 already in use

```powershell
netstat -ano | Select-String ":8082"
# Note the PID, then:
taskkill /PID <pid> /F
```

### `pages_scraped: N, chunks_indexed: 0`

Playwright browser not installed:
```powershell
cd D:\Nexo\nexo-chatbot
.venv\Scripts\playwright install chromium
```

### `status: partial` with errors in ingest response

Some pages failed to scrape (JS errors, timeouts, auth-walls). Check `errors[]` in the response — partial ingestion is non-fatal; successfully indexed pages still work.

### `mongodb: unavailable` on health check

```powershell
sc query MongoDB
net start MongoDB
```

### `qdrant: unavailable` on health check

Qdrant isn't running. Start Terminal 2, wait for `listening on 6333`, then restart the app.

### Gemini 429 quota errors

Reduce the model or add delays. In `.env`:
```env
LLM_MODEL=gemini-2.0-flash-lite
```

### `EMBEDDING_DIM mismatch`

Delete the Qdrant collection and let the app recreate it:
```bash
curl -X DELETE http://localhost:6333/collections/domain_docs
# restart the app
```

---

## One-Click Startup (Optional)

Save as `D:\Nexo\start.bat` — launches Redis + Qdrant automatically:

```bat
@echo off
echo Starting Redis...
start "Redis" "D:\Nexo\services\redis\redis-server.exe" "D:\Nexo\services\redis\redis.windows.conf"

echo Starting Qdrant...
start "Qdrant" "D:\Nexo\services\qdrant\qdrant.exe"

timeout /t 3 /nobreak > nul

echo Checking Redis...
"D:\Nexo\services\redis\redis-cli.exe" ping

echo.
echo Done. Now run in separate terminals:
echo   Terminal 3: cd D:\Nexo\nexo-chatbot ^& .venv\Scripts\activate ^& uvicorn app.main:app --host 0.0.0.0 --port 8082
echo   Terminal 4: cd D:\Nexo\chatbot-app ^& npm run dev
```
