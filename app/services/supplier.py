"""Client for the main operating system supplier API (tlv-transfers)."""
import httpx
from app.config import settings


async def assign_driver_to_booking(booking_id: str, driver_code: str) -> bool:
    """Call POST /assigndriver on the supplier API."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/assigndriver",
                json={"bookingid": int(booking_id), "drivercode": driver_code},
                headers={"Authorization": f"Bearer {settings.supplier_api_token}"},
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


async def update_booking_notes(booking_id: str, notes: str) -> bool:
    """Call POST /updatefields to log dispatch activity."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/updatefields",
                json={"bookingid": int(booking_id), "suppliernotes": notes},
                headers={"Authorization": f"Bearer {settings.supplier_api_token}"},
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False
