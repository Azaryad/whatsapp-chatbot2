"""
Manual pull from Ride Control.

Triggered when the dispatcher presses "Pull from Ride Control" on the dashboard.
Fetches assigned bookings via GET /bookings, deduplicates by external_booking_id,
creates Trip rows in 'open' status. Trips then sit in the queue waiting for the
dispatcher to drag them onto a driver region.

NOTE: Field mapping from Ride Control's response to our Trip model is best-effort.
We don't yet know the exact field names — defensive lookups try common variants.
Adjust _rc_to_trip_payload() once we see real responses.
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trip import Trip, TripSource, TripStatus
from app.models.driver import VehicleType
from app.services.supplier import list_bookings


def _pick(d: dict, *keys: str, default: Any = None) -> Any:
    """Return the first present value among keys (case-insensitive)."""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
        # try lowercase / uppercase variants
        for variant in (k.lower(), k.upper()):
            if variant in d and d[variant] not in (None, ""):
                return d[variant]
    return default


def _parse_vehicle(raw: str | None) -> VehicleType:
    """Best-effort map from Ride Control's vehicle string to our enum."""
    if not raw:
        return VehicleType.sedan
    s = raw.lower()
    if "18" in s or "minibus_18" in s:
        return VehicleType.minibus_18
    if "15" in s or "minibus" in s:
        return VehicleType.minibus_15
    if "minivan" in s and ("exec" in s or "vip" in s or "executive" in s):
        return VehicleType.executive_minivan
    if "minivan" in s or "van" in s:
        return VehicleType.minivan
    return VehicleType.sedan


def _parse_pickup_time(raw: Any) -> datetime:
    """Accept ISO 8601 string or datetime-like value."""
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _rc_to_trip_payload(rc: dict) -> dict | None:
    """Map a Ride Control booking dict to fields our Trip model expects."""
    booking_id = _pick(rc, "bookingid", "booking_id", "id")
    if booking_id is None:
        return None

    pickup_address = _pick(rc, "pickup_address", "pickupaddress", "pickup", "from_address", default="")
    pickup_city = _pick(rc, "pickup_city", "pickupcity", "from_city", default=pickup_address)
    dropoff_address = _pick(rc, "destination_address", "destinationaddress", "dropoff_address", "dropoffaddress", "destination", "to_address", default="")
    dropoff_city = _pick(rc, "destination_city", "destinationcity", "dropoff_city", "dropoffcity", "to_city", default=dropoff_address)
    pickup_time_raw = _pick(rc, "pickup_time", "pickuptime", "pickup_datetime", "datetime")
    passengers = _pick(rc, "passengers", "num_passengers", "pax", default=1)
    vehicle = _pick(rc, "vehicle_type", "vehicletype", "vehicle", "service_type", default="sedan")
    notes = _pick(rc, "notes", "special_requirements", "remarks", default="")
    price = _pick(rc, "supplier_price", "price", "amount", default=None)

    return {
        "external_booking_id": str(booking_id),
        "source": TripSource.api_push,
        "pickup_address": str(pickup_address),
        "pickup_city": str(pickup_city),
        "dropoff_address": str(dropoff_address),
        "dropoff_city": str(dropoff_city),
        "pickup_time": _parse_pickup_time(pickup_time_raw),
        "num_passengers": int(passengers) if passengers else 1,
        "vehicle_type": _parse_vehicle(str(vehicle)),
        "special_requirements": str(notes),
        "price_to_driver": float(price) if price else None,
        "status": TripStatus.open,
    }


async def pull_new_bookings(db: AsyncSession, days_ahead: int = 7) -> dict:
    """
    Fetch bookings from today through `days_ahead` days, create Trip rows for
    any external_booking_id we don't already have. Returns counts + skipped IDs.
    """
    today = datetime.now(timezone.utc).date()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=days_ahead)).isoformat()

    rc_bookings = await list_bookings(from_date, to_date)
    if not rc_bookings:
        return {"fetched": 0, "created": 0, "skipped_existing": 0, "skipped_invalid": 0, "errors": []}

    existing_ids_result = await db.execute(
        select(Trip.external_booking_id).where(Trip.external_booking_id.is_not(None))
    )
    existing_ids = {row[0] for row in existing_ids_result.all()}

    created = 0
    skipped_existing = 0
    skipped_invalid = 0
    errors: list[str] = []

    for rc in rc_bookings:
        payload = _rc_to_trip_payload(rc)
        if not payload:
            skipped_invalid += 1
            continue
        if payload["external_booking_id"] in existing_ids:
            skipped_existing += 1
            continue
        try:
            trip = Trip(**payload)
            db.add(trip)
            existing_ids.add(payload["external_booking_id"])
            created += 1
        except Exception as e:
            errors.append(f"{payload.get('external_booking_id')}: {e}")
            skipped_invalid += 1

    if created:
        await db.commit()

    return {
        "fetched": len(rc_bookings),
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "errors": errors,
    }
