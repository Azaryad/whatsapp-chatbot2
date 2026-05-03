import googlemaps
from datetime import datetime
from app.config import settings

_client: googlemaps.Client | None = None

LONG_DISTANCE_KM = 100.0


def _get_client() -> googlemaps.Client:
    global _client
    if _client is None:
        _client = googlemaps.Client(key=settings.google_maps_api_key)
    return _client


async def get_drive_info(
    origin: str,
    destination: str,
    pickup_dt: datetime,
) -> dict:
    """
    Returns {"duration_minutes": int, "distance_km": float}.
    Uses day-of-week + hour for traffic model (no exact date needed).
    Falls back to {"duration_minutes": 60, "distance_km": 0} on error.
    """
    try:
        client = _get_client()
        # Build a representative departure: next occurrence of the same weekday+hour
        departure_time = _representative_departure(pickup_dt)
        result = client.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            departure_time=departure_time,
            traffic_model="best_guess",
            language="he",
        )
        element = result["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return _fallback()
        duration_s = element.get("duration_in_traffic", element["duration"])["value"]
        distance_m = element["distance"]["value"]
        return {
            "duration_minutes": round(duration_s / 60),
            "distance_km": round(distance_m / 1000, 1),
        }
    except Exception:
        return _fallback()


def _representative_departure(dt: datetime) -> datetime:
    """
    Return a near-future datetime with the same weekday and hour as dt.
    Google Maps requires a future departure_time.
    """
    from datetime import timedelta, timezone
    now = datetime.now(timezone.utc)
    target_weekday = dt.weekday()
    target_hour = dt.hour
    days_ahead = (target_weekday - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= target_hour:
        days_ahead = 7
    candidate = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(days=days_ahead)
    return candidate


def _fallback() -> dict:
    return {"duration_minutes": 60, "distance_km": 0.0}


def is_long_distance(distance_km: float) -> bool:
    return distance_km > LONG_DISTANCE_KM
