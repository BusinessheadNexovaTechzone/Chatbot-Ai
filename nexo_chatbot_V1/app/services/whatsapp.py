import httpx
from app.config.settings import get_settings
from app.utils.logger import logger

GRAPH_API_URL = "https://graph.facebook.com/v18.0"


class WhatsAppService:

    def _settings(self):
        return get_settings()

    async def send_message(self, to: str, text: str) -> bool:
        cfg = self._settings()
        if not cfg.WHATSAPP_ACCESS_TOKEN or not cfg.WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("WhatsApp credentials not configured — message not sent")
            return False

        url = f"{GRAPH_API_URL}/{cfg.WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {cfg.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"WhatsApp send_message failed: {e}")
            return False

    def parse_inbound(self, body: dict) -> list:
        """Extract list of {from, message_id, text} dicts from a Meta webhook payload."""
        messages = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") == "text":
                        messages.append({
                            "from": msg["from"],
                            "message_id": msg["id"],
                            "text": msg["text"]["body"],
                        })
        return messages


whatsapp_service = WhatsAppService()
