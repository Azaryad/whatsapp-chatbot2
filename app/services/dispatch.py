"""
Core dispatch loop and offer state machine.

Flow per trip:
  open → filter eligible → rank with Claude → send offer to #1 driver
       → wait for reply (3h timeout)
       → accepted  → confirm, assign in supplier API, notify Michel (summary)
       → rejected  → next driver in ranked list
       → timeout   → next driver
       → exhausted → notify Michel (unassigned report)
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.driver import Driver
from app.models.trip import Trip, TripStatus
from app.models.offer import Offer, OfferStatus
from app.models.message import Message, MessageDirection
from app.services import whatsapp, claude
from app.services.app_integration import app_integration
from app.services.maps import get_drive_info
from app.services.supplier import assign_driver_to_booking
from app.utils.constraints import filter_eligible_drivers


async def start_dispatch(trip_id: int) -> None:
    """Entry point: called after a new trip is ingested."""
    async with AsyncSessionLocal() as db:
        trip = await db.get(Trip, trip_id)
        if not trip or trip.status != TripStatus.open:
            return

        info = await get_drive_info(trip.pickup_address, trip.dropoff_address, trip.pickup_time)
        trip.estimated_duration_minutes = info["duration_minutes"]
        trip.distance_km = info["distance_km"]
        await db.commit()
        await db.refresh(trip)

        eligible = await filter_eligible_drivers(trip, db)
        if not eligible:
            trip.status = TripStatus.unassigned
            await db.commit()
            await _notify_michel(trip, None, [], db)
            return

        ranked = await claude.rank_drivers(trip, eligible)
        await _offer_next(trip, ranked, [], db)


async def _offer_next(
    trip: Trip,
    ranked: list[dict],
    tried_driver_ids: list[int],
    db: AsyncSession,
) -> None:
    remaining = [r for r in ranked if r["driver_id"] not in tried_driver_ids]
    if not remaining:
        trip.status = TripStatus.unassigned
        await db.commit()
        tried_drivers = await _load_drivers(tried_driver_ids, db)
        await _notify_michel(trip, None, tried_drivers, db)
        return

    next_entry = remaining[0]
    driver = await db.get(Driver, next_entry["driver_id"])
    if not driver:
        tried_driver_ids.append(next_entry["driver_id"])
        await _offer_next(trip, ranked, tried_driver_ids, db)
        return

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.driver_offer_timeout_seconds)
    offer = Offer(
        trip_id=trip.id,
        driver_id=driver.id,
        expires_at=expires_at,
        rank_position=len(tried_driver_ids),
        rank_reason=next_entry.get("reason", ""),
    )
    db.add(offer)
    trip.status = TripStatus.offered
    await db.commit()
    await db.refresh(offer)

    from app.utils.hmac_token import sign_approval_url
    approval_link = sign_approval_url(offer.id)
    await app_integration.push_pending_trip(trip.id, driver.drivercode)
    message_body = await claude.generate_offer_message(driver, trip, approval_link)

    wa_id = await whatsapp.send_text(driver.phone, message_body)
    db.add(Message(
        driver_id=driver.id,
        direction=MessageDirection.outbound,
        wa_message_id=wa_id,
        body=message_body,
        related_offer_id=offer.id,
    ))
    await db.commit()

    # Schedule timeout job
    from app.services.scheduler import schedule_offer_timeout
    schedule_offer_timeout(offer.id, expires_at, trip.id, ranked, tried_driver_ids + [driver.id])


async def handle_driver_reply(from_phone: str, wa_message_id: str, body: str) -> None:
    """Process an inbound WhatsApp message from a driver."""
    async with AsyncSessionLocal() as db:
        driver = await _find_driver_by_phone(from_phone, db)
        if not driver:
            return

        pending_offer = await _get_pending_offer(driver.id, db)
        if not pending_offer:
            return

        trip = await db.get(Trip, pending_offer.trip_id)
        db.add(Message(
            driver_id=driver.id,
            direction=MessageDirection.inbound,
            wa_message_id=wa_message_id,
            body=body,
            related_offer_id=pending_offer.id,
        ))
        pending_offer.driver_reply_text = body

        interpretation = await claude.interpret_reply(driver.name, body)
        intent = interpretation.get("intent", "ambiguous")
        pending_offer.ai_interpretation = intent
        await db.commit()

        if intent == "yes":
            await _accept_offer(pending_offer, driver, trip, db)
        elif intent == "no":
            await _reject_offer(pending_offer, driver, trip, db)
        else:
            clarification = interpretation.get("clarification_needed")
            if clarification:
                wa_id = await whatsapp.send_text(driver.phone, clarification)
                db.add(Message(
                    driver_id=driver.id,
                    direction=MessageDirection.outbound,
                    wa_message_id=wa_id,
                    body=clarification,
                    related_offer_id=pending_offer.id,
                ))
                await db.commit()


async def _accept_offer(offer: Offer, driver: Driver, trip: Trip, db: AsyncSession) -> None:
    from app.services.scheduler import cancel_offer_timeout
    from app.services.approval import schedule_approval_check
    cancel_offer_timeout(offer.id)

    offer.status = OfferStatus.pending_approval
    await db.commit()

    schedule_approval_check(offer.id)

    from app.utils.hmac_token import sign_approval_url
    approval_link = sign_approval_url(offer.id)
    confirmation = (
        f"מעולה {driver.name.split()[0]}! אנחנו עוד צריכים אישור רשמי שלך. "
        f"לחץ על הלינק כדי לאשר: {approval_link}"
    )
    wa_id = await whatsapp.send_text(driver.phone, confirmation)
    db.add(Message(
        driver_id=driver.id,
        direction=MessageDirection.outbound,
        wa_message_id=wa_id,
        body=confirmation,
        related_offer_id=offer.id,
    ))
    await db.commit()


async def _reject_offer(offer: Offer, driver: Driver, trip: Trip, db: AsyncSession) -> None:
    from app.services.scheduler import cancel_offer_timeout, get_ranked_list
    cancel_offer_timeout(offer.id)
    await app_integration.cancel_pending_trip(trip.id, driver.drivercode)

    offer.status = OfferStatus.rejected
    await db.commit()

    farewell = await claude.generate_rejection_followup(driver.name)
    wa_id = await whatsapp.send_text(driver.phone, farewell)
    db.add(Message(
        driver_id=driver.id,
        direction=MessageDirection.outbound,
        wa_message_id=wa_id,
        body=farewell,
        related_offer_id=offer.id,
    ))
    trip.status = TripStatus.open
    await db.commit()

    ranked, tried = get_ranked_list(offer.id)
    if ranked:
        await _offer_next(trip, ranked, tried, db)


async def handle_offer_timeout(
    offer_id: int,
    trip_id: int,
    ranked: list[dict],
    tried_driver_ids: list[int],
) -> None:
    async with AsyncSessionLocal() as db:
        offer = await db.get(Offer, offer_id)
        if not offer or offer.status != OfferStatus.pending:
            return

        driver = await db.get(Driver, offer.driver_id)
        trip = await db.get(Trip, trip_id)
        if driver:
            await app_integration.cancel_pending_trip(trip_id, driver.drivercode)

        offer.status = OfferStatus.timeout
        trip.status = TripStatus.open
        await db.commit()

        if driver:
            timeout_msg = f"הי {driver.name.split()[0]}, לא קיבלנו תשובה, עברנו לנהג אחר. יום טוב!"
            wa_id = await whatsapp.send_text(driver.phone, timeout_msg)
            db.add(Message(
                driver_id=driver.id,
                direction=MessageDirection.outbound,
                wa_message_id=wa_id,
                body=timeout_msg,
                related_offer_id=offer.id,
            ))
            await db.commit()

        await _offer_next(trip, ranked, tried_driver_ids, db)


async def _notify_michel(
    trip: Trip,
    accepted_driver: Driver | None,
    tried_drivers: list[Driver],
    db: AsyncSession,
) -> None:
    report = await claude.generate_michel_report(trip, accepted_driver, tried_drivers)
    michel_phone = settings.michel_phone
    await whatsapp.send_text(michel_phone, report)


async def _find_driver_by_phone(phone: str, db: AsyncSession) -> Driver | None:
    from app.services.whatsapp import _normalize_phone
    normalized = _normalize_phone(phone)
    stmt = select(Driver).where(Driver.phone.contains(normalized[-9:]))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_pending_offer(driver_id: int, db: AsyncSession) -> Offer | None:
    stmt = (
        select(Offer)
        .where(Offer.driver_id == driver_id, Offer.status == OfferStatus.pending)
        .order_by(Offer.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_tried_driver_ids(trip_id: int, db: AsyncSession) -> list[int]:
    stmt = select(Offer.driver_id).where(Offer.trip_id == trip_id)
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def _load_drivers(driver_ids: list[int], db: AsyncSession) -> list[Driver]:
    if not driver_ids:
        return []
    stmt = select(Driver).where(Driver.id.in_(driver_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())
