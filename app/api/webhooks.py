from fastapi import APIRouter, Request, Response, HTTPException, BackgroundTasks
from app.config import settings
from app.services.whatsapp import parse_webhook
from app.services.dispatch import handle_driver_reply

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification (one-time setup)."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks):
    """Receive inbound WhatsApp messages."""
    payload = await request.json()
    messages = parse_webhook(payload)
    for msg in messages:
        background.add_task(
            handle_driver_reply,
            msg["from_phone"],
            msg["wa_message_id"],
            msg["body"],
        )
    return {"status": "ok"}
