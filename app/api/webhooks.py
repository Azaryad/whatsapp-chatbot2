from fastapi import APIRouter, Request, Response, HTTPException, BackgroundTasks
from app.config import settings
from app.services.whatsapp import parse_webhook

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks):
    """Route inbound WhatsApp messages to the correct handler."""
    payload = await request.json()
    messages = parse_webhook(payload)

    for msg in messages:
        background.add_task(_route_message, msg)

    return {"status": "ok"}


async def _route_message(msg: dict) -> None:
    """Determine whether the sender is a driver or supplier and dispatch accordingly."""
    from app.database import AsyncSessionLocal
    from app.services.batch_dispatch import (
        _find_driver_by_phone,
        _find_supplier_by_phone,
        handle_driver_batch_reply,
        handle_supplier_reply,
    )
    async with AsyncSessionLocal() as db:
        driver = await _find_driver_by_phone(msg["from_phone"], db)
        supplier = await _find_supplier_by_phone(msg["from_phone"], db)

    if driver:
        await handle_driver_batch_reply(
            msg["from_phone"], msg["wa_message_id"], msg["body"]
        )
    elif supplier:
        await handle_supplier_reply(
            msg["from_phone"], msg["wa_message_id"], msg["body"]
        )
    # Unknown sender — silently ignore
