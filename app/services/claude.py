import json
import anthropic
from app.config import settings
from app.models.driver import Driver
from app.models.trip import Trip

_client: anthropic.AsyncAnthropic | None = None

MODEL = "claude-sonnet-4-6"

FALLBACK_OFFER_TEMPLATES = [
    "היי {name}, יש נסיעה ב{day} בשעה {time} מ{pickup} ל{dropoff}, {pax} נוסעים. שווה לך? פרטים ואישור: {link}",
]

FALLBACK_REJECTION = "תודה {name}! עברתי לנהג אחר. יום טוב 🙏"


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def rank_drivers(trip: Trip, eligible_drivers: list[Driver]) -> list[dict]:
    """
    Returns list of {"driver_id": int, "reason": str} sorted best-first.
    Falls back to original order if Claude is unreachable.
    """
    if not eligible_drivers:
        return []

    drivers_payload = [
        {
            "driver_id": d.id,
            "name": d.name,
            "home_city": d.home_city,
            "vehicle_type": d.vehicle_type,
            "region": d.region,
        }
        for d in eligible_drivers
    ]

    prompt = f"""You are a dispatcher for an Israeli tourism transport company.
Rank the following drivers for this trip, best match first.

Trip:
- Pickup: {trip.pickup_city} ({trip.pickup_address})
- Dropoff: {trip.dropoff_city} ({trip.dropoff_address})
- Time: {trip.pickup_time.strftime('%A %H:%M')}
- Passengers: {trip.num_passengers}
- Vehicle required: {trip.vehicle_type}
- Distance: {trip.distance_km or '?'} km

Drivers:
{json.dumps(drivers_payload, ensure_ascii=False, indent=2)}

Ranking criteria (in order of priority):
1. Driver whose home_city is geographically closest to the pickup city (use your knowledge of Israeli geography).
2. Fairness: prefer drivers who haven't worked recently.
3. Cool-off: deprioritize drivers who rejected or timed out on their last offer.

Return ONLY valid JSON, no markdown, no explanation outside JSON:
{{"ranked": [{{"driver_id": <int>, "reason": "<one line in English>"}}]}}"""

    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system="You are a helpful dispatcher assistant. Always reply with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        data = json.loads(text)
        return data["ranked"]
    except Exception:
        return [{"driver_id": d.id, "reason": "fallback order"} for d in eligible_drivers]


async def generate_offer_message(driver: Driver, trip: Trip, link: str) -> str:
    """Generate a casual Hebrew WhatsApp offer message."""
    day_he = _day_hebrew(trip.pickup_time.weekday())
    time_str = trip.pickup_time.strftime("%H:%M")

    prompt = f"""You are a friendly Israeli dispatcher sending a WhatsApp message to a driver.
Write a SHORT, casual Hebrew message (2-3 lines max) offering this trip.
Feel like a human dispatcher, not a robot. Use informal Hebrew.

Driver first name: {driver.name.split()[0]}
Trip: {day_he} at {time_str}, from {trip.pickup_city} to {trip.dropoff_city}, {trip.num_passengers} passengers
Price: {f'₪{trip.price_to_driver:.0f}' if trip.price_to_driver else 'לא צוין'}
Link for full details and confirmation: {link}

Rules:
- Start with היי + first name
- Mention day, time, route, passengers
- Include the link at the end
- End with a question like שווה לך? or מתאים?
- Do NOT use emojis
- Reply with the message text only, no quotes"""

    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        t = FALLBACK_OFFER_TEMPLATES[0]
        return t.format(
            name=driver.name.split()[0],
            day=day_he,
            time=time_str,
            pickup=trip.pickup_city,
            dropoff=trip.dropoff_city,
            pax=trip.num_passengers,
            link=link,
        )


async def interpret_reply(driver_name: str, reply_text: str, context: str = "") -> dict:
    """
    Classify a driver's Hebrew reply.
    Returns {"intent": "yes"|"no"|"ambiguous", "clarification_needed": str|None}
    """
    prompt = f"""A driver named {driver_name} replied to a trip offer on WhatsApp.
Their message (in Hebrew): "{reply_text}"
{f'Context: {context}' if context else ''}

Classify the intent:
- "yes" — clear acceptance (e.g. "כן", "אוקי", "מאשר", "אני בא")
- "no" — clear rejection (e.g. "לא", "לא יכול", "תעביר", "לא פנוי")
- "ambiguous" — needs clarification (e.g. "אולי", "תלוי", "כמה?", unclear)

Return ONLY valid JSON:
{{"intent": "<yes|no|ambiguous>", "clarification_needed": "<question to ask driver in Hebrew, or null>"}}"""

    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=200,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.content[0].text.strip())
    except Exception:
        return {"intent": "ambiguous", "clarification_needed": "האם אתה מאשר את הנסיעה? כן או לא?"}


async def generate_rejection_followup(driver_name: str) -> str:
    """Generate a polite Hebrew message when moving to the next driver."""
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content":
                f"Write a very short, polite Hebrew WhatsApp message thanking driver {driver_name.split()[0]} "
                f"for their response and letting them know we moved on. 1 line. No emojis. Text only."}],
        )
        return response.content[0].text.strip()
    except Exception:
        return FALLBACK_REJECTION.format(name=driver_name.split()[0])


async def generate_michel_report(
    trip: Trip,
    accepted_driver: Driver | None,
    exhausted_drivers: list[Driver],
) -> str:
    """Generate a Hebrew WhatsApp report for Michel."""
    status = f"נסיעה #{trip.id} — {trip.pickup_city} → {trip.dropoff_city}, {trip.pickup_time.strftime('%A %d/%m %H:%M')}\n"
    if accepted_driver:
        status += f"שויך: {accepted_driver.name} ({accepted_driver.phone})\n"
    else:
        status += "לא שויך נהג — כל הנהגים האזוריים נוסו\n"
    tried = ", ".join(d.name for d in exhausted_drivers)
    status += f"ניסו: {tried}"
    return status


def _day_hebrew(weekday: int) -> str:
    days = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]
    return days[weekday]


async def rank_drivers_for_batch(trips: list[Trip], drivers: list[Driver]) -> list[dict]:
    """Rank drivers for a batch of trips. Returns [{"driver_id": int, "reason": str}]."""
    if not drivers:
        return []
    trips_payload = [
        {"trip_id": t.id, "pickup_city": t.pickup_city, "dropoff_city": t.dropoff_city,
         "pickup_time": t.pickup_time.strftime("%A %H:%M"), "passengers": t.num_passengers,
         "vehicle": t.vehicle_type}
        for t in trips
    ]
    drivers_payload = [
        {"driver_id": d.id, "name": d.name, "home_city": d.home_city,
         "vehicle_type": d.vehicle_type, "region": d.region}
        for d in drivers
    ]
    prompt = (
        f"Rank these drivers for the following batch of trips. Best overall fit first.\n\n"
        f"Trips:\n{json.dumps(trips_payload, ensure_ascii=False)}\n\n"
        f"Drivers:\n{json.dumps(drivers_payload, ensure_ascii=False)}\n\n"
        f"Criteria: proximity to pickup cities, fairness rotation, cool-off for recent rejections.\n"
        f'Return ONLY JSON: {{"ranked": [{{"driver_id": <int>, "reason": "<one line>"}}]}}'
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL, max_tokens=1024,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.content[0].text.strip())["ranked"]
    except Exception:
        return [{"driver_id": d.id, "reason": "fallback"} for d in drivers]


async def generate_batch_offer_message(driver: Driver, trips: list[Trip]) -> str:
    """Generate a Hebrew WhatsApp message offering multiple rides to a driver."""
    trips_text = "\n".join(
        f"{i+1}. {_day_hebrew(t.pickup_time.weekday())} {t.pickup_time.strftime('%H:%M')} "
        f"{t.pickup_city}→{t.dropoff_city} ({t.num_passengers} נוסעים)"
        for i, t in enumerate(trips)
    )
    prompt = (
        f"Write a short casual Hebrew WhatsApp message offering {len(trips)} rides to driver "
        f"{driver.name.split()[0]}.\n\nRides:\n{trips_text}\n\n"
        f"Ask them to reply with the ride number and yes/no for each. "
        f"Friendly dispatcher tone. No emojis. Text only. 4 lines max."
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return f"היי {driver.name.split()[0]}, יש לך {len(trips)} נסיעות:\n{trips_text}\nענה לכל נסיעה כן/לא."


async def parse_batch_reply(driver_name: str, reply: str, trips: list[Trip]) -> dict:
    """
    Parse a driver's reply to a batch offer.
    Returns {"per_ride": ["yes"|"no"|"ambiguous", ...]} — one entry per trip in order.
    """
    trips_text = "\n".join(
        f"{i+1}. {t.pickup_city}→{t.dropoff_city} {t.pickup_time.strftime('%d/%m %H:%M')}"
        for i, t in enumerate(trips)
    )
    prompt = (
        f"Driver {driver_name} received {len(trips)} ride offers and replied:\n\"{reply}\"\n\n"
        f"Rides offered:\n{trips_text}\n\n"
        f"Classify their intent for EACH ride as yes/no/ambiguous.\n"
        f'Return ONLY JSON: {{"per_ride": ["yes"|"no"|"ambiguous", ...]}} — exactly {len(trips)} entries.'
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL, max_tokens=200,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(response.content[0].text.strip())
        per_ride = data.get("per_ride", [])
        while len(per_ride) < len(trips):
            per_ride.append("ambiguous")
        return {"per_ride": per_ride[:len(trips)]}
    except Exception:
        return {"per_ride": ["ambiguous"] * len(trips)}


async def parse_supplier_reply(reply: str, booking_ids: list[str]) -> dict:
    """
    Parse a supplier's reply mapping booking IDs to confirm/decline.
    Returns {"booking_id": "confirm"|"decline"|"unknown", ...}
    """
    prompt = (
        f"A supplier replied to a ride offer:\n\"{reply}\"\n\n"
        f"Booking IDs in the offer: {booking_ids}\n\n"
        f"For each booking ID, determine if the supplier confirmed or declined it.\n"
        f'Return ONLY JSON: {{"<booking_id>": "confirm"|"decline"|"unknown", ...}}'
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL, max_tokens=300,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.content[0].text.strip())
    except Exception:
        return {bid: "unknown" for bid in booking_ids}


async def generate_approval_reminder(name: str, trips: list[Trip]) -> str:
    """Remind a driver/supplier to click the Ride Control approval link."""
    trips_text = ", ".join(
        f"{t.pickup_city}→{t.dropoff_city} {t.pickup_time.strftime('%H:%M')}"
        for t in trips
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=MODEL, max_tokens=120,
            messages=[{"role": "user", "content":
                f"Write a short Hebrew WhatsApp reminder to {name.split()[0]} that they said yes "
                f"to these rides but haven't clicked the approval link yet: {trips_text}. "
                f"Friendly but urgent. 2 lines max. No emojis."}],
        )
        return response.content[0].text.strip()
    except Exception:
        return f"היי {name.split()[0]}, אישרת את הנסיעות אך טרם לחצת על הלינק לאישור. נא לאשר בהקדם."
