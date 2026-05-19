from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config.settings import get_settings
from app.models.schemas import ChatRequest
from app.services.orchestrator import orchestrator
from app.services.whatsapp import whatsapp_service
from app.utils.logger import logger

router = APIRouter(prefix="/api/v1/whatsapp", tags=["whatsapp"])


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake (called once when registering the webhook URL)."""
    cfg = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == cfg.WHATSAPP_VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook", status_code=200)
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive inbound WhatsApp messages from Meta.
    Always returns 200 immediately — processing happens in the background.
    Meta retries delivery if it doesn't receive 200 within 20 s.
    """
    body = await request.json()
    messages = whatsapp_service.parse_inbound(body)
    for msg in messages:
        background_tasks.add_task(_process_whatsapp_message, msg["from"], msg["text"])
    return {"status": "ok"}


async def _process_whatsapp_message(sender_phone: str, text: str):
    """Run the full RAG pipeline for one WhatsApp message and reply to the sender."""
    try:
        # Reuse the same orchestrator as the web chat; phone number is the session_id
        chat_request = ChatRequest(query=text, session_id=sender_phone, stream=False)
        response = await orchestrator.handle(chat_request)
        await whatsapp_service.send_message(to=sender_phone, text=response.answer)
    except Exception as exc:
        logger.error(f"WhatsApp message processing failed for {sender_phone}: {exc}", exc_info=True)
        await whatsapp_service.send_message(
            to=sender_phone,
            text="Sorry, something went wrong. Please try again.",
        )
