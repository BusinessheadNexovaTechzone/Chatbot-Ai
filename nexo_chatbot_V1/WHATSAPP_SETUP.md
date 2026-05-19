# WhatsApp Integration — Setup Guide

Nexo Chatbot supports WhatsApp as a second input channel alongside the web UI. Both channels share the same RAG pipeline, conversation history store (MongoDB), and Redis cache. This document covers everything needed to go from zero to a working WhatsApp bot.

---

## Architecture Overview

```
WhatsApp User
     │
     │  (sends message)
     ▼
Meta Cloud API
     │
     │  POST /api/v1/whatsapp/webhook
     ▼
FastAPI Backend
     │
     ├─ parse_inbound()          extract sender phone + message text
     ├─ orchestrator.handle()    same RAG pipeline as web chat
     │       ├─ Intent classification (Gemini)
     │       ├─ Domain retrieval (Qdrant) / Web search / General LLM
     │       └─ Save encrypted history to MongoDB (session_id = phone number)
     └─ whatsapp_service.send_message()   reply via Meta Cloud API
```

Web users also see a **"Chat on WhatsApp"** button in the chat header that opens `wa.me/<business-number>` — letting them continue the conversation on WhatsApp.

---

## Prerequisites

- A **Meta Developer account** — [developers.facebook.com](https://developers.facebook.com)
- A **Meta App** with the **WhatsApp** product added
- A **WhatsApp Business Account (WABA)** linked to the app
- A **phone number** registered in the Meta App (can be the free test number during development)
- Your backend must be reachable over **HTTPS** on a public URL (Meta will not call `localhost`)
  - Use [ngrok](https://ngrok.com) for local testing: `ngrok http 8081`

---

## Step 1 — Get Credentials from Meta App Dashboard

1. Go to **Meta App Dashboard → WhatsApp → API Setup**
2. Note down:
   | Value | Where to find it |
   |-------|-----------------|
   | **Phone Number ID** | Shown under "From" in the API Setup section |
   | **WhatsApp Business Account ID** | Shown on the same page |
   | **Temporary Access Token** | Shown under "Access Token" (valid 24 h — replace with a permanent one for production) |

3. For a **permanent access token** (production):
   - Create a **System User** in Meta Business Settings
   - Assign the system user to the WhatsApp app with `whatsapp_business_messaging` permission
   - Generate a token for that system user — it does not expire

---

## Step 2 — Configure Environment Variables

### Backend — `.env`

```env
# ── WhatsApp Business API ─────────────────────────────────────────────────────
WHATSAPP_VERIFY_TOKEN=my-secret-verify-token   # any string you choose — used only for webhook registration
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxx...           # Meta system-user access token
WHATSAPP_PHONE_NUMBER_ID=123456789012345       # Phone Number ID from Meta App Dashboard
```

> `WHATSAPP_VERIFY_TOKEN` is a **secret you invent** — it is not issued by Meta. You enter the same string in both your `.env` and the Meta Dashboard webhook form (Step 3).

### Frontend — `chatbot_ui_08/.env.local`

```env
# WhatsApp business number in E.164 format WITHOUT the leading +
# Example: +91 98765 43210  →  919876543210
VITE_WHATSAPP_NUMBER=919876543210
```

Rebuild the frontend after changing this (`npm run build`).

---

## Step 3 — Register the Webhook with Meta

1. In **Meta App Dashboard → WhatsApp → Configuration**, click **Edit** next to "Webhook".
2. Fill in:
   | Field | Value |
   |-------|-------|
   | **Callback URL** | `https://your-domain.com/api/v1/whatsapp/webhook` |
   | **Verify Token** | Same string you set as `WHATSAPP_VERIFY_TOKEN` in `.env` |
3. Click **Verify and Save** — Meta sends a `GET` request to your callback URL. The server reads `hub.verify_token`, compares it, and returns `hub.challenge`. If it matches, the webhook is registered.
4. Under **Webhook Fields**, enable **`messages`** — this triggers the `POST` on incoming messages.

> For local development with ngrok:
> ```powershell
> ngrok http 8081
> # Use the https://xxxx.ngrok.io URL as your Callback URL
> ```

---

## Step 4 — Verify It Works

### Webhook Verification (GET)

```powershell
# Simulate what Meta sends during webhook registration
curl "https://your-domain.com/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=my-secret-verify-token&hub.challenge=CHALLENGE_STRING"
# Expected: CHALLENGE_STRING (plain text, 200 OK)
```

### Inbound Message (POST)

```powershell
# Simulate an incoming WhatsApp message
curl -X POST https://your-domain.com/api/v1/whatsapp/webhook `
  -H "Content-Type: application/json" `
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "919876543210",
            "id": "wamid.test001",
            "type": "text",
            "text": { "body": "What services does Nexo offer?" }
          }]
        }
      }]
    }]
  }'
# Expected: {"status":"ok"}  (reply is sent asynchronously to the sender)
```

### Send a Message (direct API call)

```powershell
curl -X POST https://your-domain.com/api/v1/whatsapp/send `
  -H "Content-Type: application/json" `
  -d '{"to": "919876543210", "text": "Hello from Nexo!"}'
```

---

## Relevant Source Files

| File | Purpose |
|------|---------|
| `app/api/routes/whatsapp.py` | `GET /webhook` (verification) + `POST /webhook` (inbound) + `POST /send` |
| `app/services/whatsapp.py` | `WhatsAppService` — `send_message()` and `parse_inbound()` |
| `app/config/settings.py` | `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` |
| `chatbot_ui_08/src/components/ChatHeader.jsx` | "Chat on WhatsApp" button (shown when `VITE_WHATSAPP_NUMBER` is set) |
| `chatbot_ui_08/src/App.jsx` | Reads `VITE_WHATSAPP_NUMBER` and passes it to `ChatContainer` |
| `chatbot_ui_08/src/widget-entry.jsx` | Widget: pass `config.whatsappNumber` to enable button in embedded mode |

---

## How the Inbound Flow Works (Code Level)

1. **Meta POSTs** to `POST /api/v1/whatsapp/webhook`.
2. The handler calls `whatsapp_service.parse_inbound(body)` to extract a list of `{from, message_id, text}` dicts.
3. Each message is queued as a **FastAPI `BackgroundTask`** so `200 OK` is returned to Meta immediately (Meta retries if it doesn't get 200 within 20 s).
4. `_process_whatsapp_message(sender_phone, text)` builds a `ChatRequest` using the **sender's phone number as `session_id`**.
5. `orchestrator.handle(request)` runs the full intent → retrieval → generation pipeline, fetching and saving conversation history from MongoDB using the phone number.
6. `whatsapp_service.send_message(to=sender_phone, text=response.answer)` POSTs the reply to `https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`.

---

## Web → WhatsApp Handoff

The **"Chat on WhatsApp"** button in the chat header lets web users switch to WhatsApp:

- It only appears when `VITE_WHATSAPP_NUMBER` is set in the frontend `.env.local`.
- It opens `https://wa.me/<number>` in a new tab — on mobile this launches the WhatsApp app directly.
- In the embedded widget, pass `whatsappNumber` in the init config:

```html
<script src="/chatbot.iife.js"></script>
<script>
  ChatBot.init({
    apiUrl: "https://your-domain.com",
    wsUrl:  "wss://your-domain.com",
    whatsappNumber: "919876543210"   // shows the WhatsApp button
  });
</script>
```

---

## Session Identity & Shared History

| Channel | `session_id` value | History scope |
|---------|-------------------|---------------|
| Web chat | UUID (stored in `sessionStorage`) | Per browser tab/session |
| WhatsApp | Sender's E.164 phone number (e.g. `919876543210`) | Per phone number, persistent across conversations |

Both channels read/write to the same MongoDB `chats` collection. A WhatsApp user's entire conversation history is available whenever they message the bot again, regardless of time gap.

---

## Production Checklist

- [ ] Replace the 24-hour temporary access token with a permanent system-user token
- [ ] Set `WHATSAPP_VERIFY_TOKEN` to a long random string (not a guessable word)
- [ ] Backend is deployed behind HTTPS (Meta rejects plain HTTP webhook URLs)
- [ ] `WHATSAPP_PHONE_NUMBER_ID` matches the production phone number (not the test number)
- [ ] Webhook field `messages` is subscribed in Meta App Dashboard
- [ ] `VITE_WHATSAPP_NUMBER` is set and frontend is rebuilt
- [ ] Test end-to-end by sending a real WhatsApp message to the business number
