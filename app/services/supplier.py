"""
Client for the Ride Control supplier API.

Authentication (per https://ridecontrolapi.tlv-transfers.com/doc):
  X-Api-Key:    64-char hex API key issued by Ride Control admin
  X-Timestamp:  unix seconds, must be within 5 minutes of server time
  X-Signature:  hex(HMAC-SHA256(api_secret, timestamp + "\\n" + body))

The body used for the signature MUST be the exact bytes sent over the wire
(no re-serialisation by httpx). For GET requests the body is the empty string.
"""
import hmac
import hashlib
import time
import json
import httpx

from app.config import settings


def _sign(timestamp: str, body: str) -> str:
    payload = f"{timestamp}\n{body}".encode()
    secret = settings.supplier_api_secret.encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _signed_headers(body: str = "") -> dict:
    timestamp = str(int(time.time()))
    return {
        "X-Api-Key": settings.supplier_api_key,
        "X-Timestamp": timestamp,
        "X-Signature": _sign(timestamp, body),
        "Content-Type": "application/json",
    }


# ─── Write operations ────────────────────────────────────────────────────────

async def assign_driver_to_booking(booking_id: str, driver_code: str) -> bool:
    """POST /assigndriver — assign a driver to a booking."""
    body = json.dumps(
        {"bookingid": int(booking_id), "drivercode": driver_code},
        separators=(",", ":"),
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/assigndriver",
                content=body.encode(),
                headers=_signed_headers(body),
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


async def update_booking_notes(booking_id: str, notes: str) -> bool:
    """POST /updatefields — write supplier notes onto a booking."""
    body = json.dumps(
        {"bookingid": int(booking_id), "suppliernotes": notes},
        separators=(",", ":"),
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/updatefields",
                content=body.encode(),
                headers=_signed_headers(body),
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


async def report_status(
    booking_id: str,
    status: str,
    driver_code: str,
    latitude: float,
    longitude: float,
    error_radius: float | None = None,
    note: str | None = None,
) -> bool:
    """
    POST /reportstatus — report driver GPS + status. Sequential workflow:
    GoingForPickup → ArrivedAtPickup → RidingToDropOff → AtDestination | CustomerNoShow
    """
    payload: dict = {
        "bookingid": int(booking_id),
        "status": status,
        "drivercode": driver_code,
        "latitude": latitude,
        "longitude": longitude,
    }
    if error_radius is not None:
        payload["errorradius"] = error_radius
    if note is not None:
        payload["note"] = note
    body = json.dumps(payload, separators=(",", ":"))
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/reportstatus",
                content=body.encode(),
                headers=_signed_headers(body),
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


async def change_booking_status(booking_id: str, status: str, note: str | None = None) -> bool:
    """POST /changestatus — confirm/reject changes (RQ_OK, RQ_RJ, CH_OK, CH_RJ, CX_OK)."""
    payload: dict = {"bookingid": int(booking_id), "status": status}
    if note is not None:
        payload["note"] = note
    body = json.dumps(payload, separators=(",", ":"))
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/changestatus",
                content=body.encode(),
                headers=_signed_headers(body),
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


# ─── Read operations ─────────────────────────────────────────────────────────

async def list_bookings(from_date: str, to_date: str, status: str | None = None) -> list[dict]:
    """
    GET /bookings — list bookings assigned to us in a date range.
    Dates are YYYY-MM-DD strings. Returns [] on error.
    """
    params: dict = {"from": from_date, "to": to_date}
    if status:
        params["status"] = status
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.supplier_api_base}/bookings",
                params=params,
                headers=_signed_headers(""),
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Some APIs wrap the list under "data" or "bookings"
                for key in ("data", "bookings", "items"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return []
    except Exception:
        return []


async def get_booking(booking_id: str) -> dict | None:
    """GET /booking?bookingid=X — fetch full details of one booking."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.supplier_api_base}/booking",
                params={"bookingid": int(booking_id)},
                headers=_signed_headers(""),
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception:
        return None


async def list_drivers() -> list[dict]:
    """GET /drivers — fetch all drivers under our supplier account."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.supplier_api_base}/drivers",
                headers=_signed_headers(""),
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("data", "drivers"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return []
    except Exception:
        return []


async def upsert_driver(
    driver_code: str, name: str, password: str, mobile: str, active: bool
) -> bool:
    """POST /driver — create or update a driver record on Ride Control's side."""
    body = json.dumps(
        {
            "drivercode": driver_code,
            "drivername": name,
            "password": password,
            "mobile": mobile,
            "active": 1 if active else 0,
        },
        separators=(",", ":"),
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.supplier_api_base}/driver",
                content=body.encode(),
                headers=_signed_headers(body),
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False
