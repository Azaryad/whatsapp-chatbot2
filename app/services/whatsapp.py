import httpx
from app.config import settings


GRAPH_URL = "https://graph.facebook.com/v21.0"


async def send_text(phone: str, body: str) -> str:
    """Send a WhatsApp text message. Returns the WA message ID."""
    # Normalize Israeli numbers: 05xx → 9725xx
    wa_number = _normalize_phone(phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_number,
        "type": "text",
        "text": {"body": body},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_URL}/{settings.wa_phone_number_id}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["messages"][0]["id"]


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace("-", "").replace(" ", "")
    if phone.startswith("0"):
        phone = "972" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]
    return phone


def parse_webhook(payload: dict) -> list[dict]:
    """
    Extract inbound messages from a WhatsApp webhook payload.
    Returns list of dicts: {from_phone, wa_message_id, body, timestamp}
    """
    results = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") == "text":
                    results.append({
                        "from_phone": msg["from"],
                        "wa_message_id": msg["id"],
                        "body": msg["text"]["body"],
                        "timestamp": int(msg.get("timestamp", 0)),
                    })
    return results
