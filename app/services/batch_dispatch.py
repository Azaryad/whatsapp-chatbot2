"""
Batch dispatch service.

Driver flow:
  Dispatcher drags N rides into a driver-region box → sends.
  System packs non-conflicting rides per driver (greedy, Claude-ranked).
  One WhatsApp per driver listing their rides.
  Driver replies per-ride (or "all yes" / "all no").
  Refused rides are immediately re-offered to next best driver.
  When all rides resolved or all drivers exhausted → Michel report.

Supplier flow:
  Dispatcher drags N rides into a supplier box → sends.
  One WhatsApp to supplier listing all rides + Ride Control approval link per ride.
  Supplier replies per booking ID.
  Unconfirmed after 6h → Michel report.
"""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.driver import Driver
from app.models.supplier import Supplier
from app.models.trip import Trip, TripStatus
from app.models.offer import Offer, OfferStatus
from app.models.batch_offer import BatchOffer, BatchType, BatchStatus
from app.models.message import Message, MessageDirection
from app.services import whatsapp, claude
from app.services.supplier import assign_driver_to_booking
from app.services.scheduler import scheduler


# ─── Driver batch dispatch ────────────────────────────────────────────────────

async def dispatch_driver_batch(trip_ids: list[int], region: str, db: AsyncSession) -> dict:
    """
    Called when dispatcher sends a set of rides to a driver region queue.
    Returns {"batches_sent": int, "trips_pending": list[int]}.
    """
    trips = await _load_trips(trip_ids, db)
    if not trips:
        return {"batches_sent": 0, "trips_pending": []}

    drivers = await _load_region_drivers(region, db)
    if not drivers:
        await _notify_michel_unassigned(trips, [], db)
        return {"batches_sent": 0, "trips_pending": trip_ids}

    ranked = await claude.rank_drivers_for_batch(trips, drivers)
    remaining_trips = list(trips)
    batches_sent = 0

    for driver_entry in ranked:
        if not remaining_trips:
            break
        driver = await db.get(Driver, driver_entry["driver_id"])
        if not driver:
            continue
        assignable = _pack_trips(remaining_trips, driver)
        if not assignable:
            continue

        await _send_driver_batch(driver, assignable, db)
        batches_sent += 1
        for t in assignable:
            remaining_trips.remove(t)

    if remaining_trips:
        await _notify_michel_unassigned(remaining_trips, [], db)

    return {"batches_sent": batches_sent, "trips_pending": [t.id for t in remaining_trips]}


async def _send_driver_batch(driver: Driver, trips: list[Trip], db: AsyncSession) -> BatchOffer:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.driver_offer_timeout_seconds)
    batch = BatchOffer(
        batch_type=BatchType.driver,
        driver_id=driver.id,
        expires_at=expires_at,
    )
    db.add(batch)
    await db.flush()

    for trip in trips:
        offer = Offer(
            trip_id=trip.id,
            driver_id=driver.id,
            batch_offer_id=batch.id,
            expires_at=expires_at,
        )
        db.add(offer)
        trip.status = TripStatus.offered

    await db.commit()
    await db.refresh(batch)

    message_body = await claude.generate_batch_offer_message(driver, trips)
    wa_id = await whatsapp.send_text(driver.phone, message_body)
    batch.wa_message_id = wa_id

    db.add(Message(
        driver_id=driver.id,
        direction=MessageDirection.outbound,
        wa_message_id=wa_id,
        body=message_body,
        related_offer_id=None,
    ))
    await db.commit()

    scheduler.add_job(
        _driver_batch_timeout,
        trigger="date",
        run_date=expires_at,
        id=f"batch_timeout_{batch.id}",
        kwargs={"batch_id": batch.id},
        replace_existing=True,
        misfire_grace_time=300,
    )
    return batch


async def handle_driver_batch_reply(from_phone: str, wa_message_id: str, body: str) -> None:
    """Parse a driver's reply to a batch offer and resolve each ride."""
    async with AsyncSessionLocal() as db:
        driver = await _find_driver_by_phone(from_phone, db)
        if not driver:
            await _check_restriction_update(from_phone, body)
            return

        batch = await _get_pending_driver_batch(driver.id, db)
        if not batch:
            await _check_restriction_update_for_driver(driver, body, db)
            return

        db.add(Message(
            driver_id=driver.id,
            direction=MessageDirection.inbound,
            wa_message_id=wa_message_id,
            body=body,
        ))
        batch.raw_reply = body
        await db.commit()

        offers = await _get_batch_offers(batch.id, db)
        trips = [await db.get(Trip, o.trip_id) for o in offers]

        parsed = await claude.parse_batch_reply(driver.name, body, trips)

        refused_trips: list[Trip] = []
        for offer, trip, intent in zip(offers, trips, parsed["per_ride"]):
            if intent == "yes":
                offer.status = OfferStatus.accepted
                offer.ai_interpretation = "yes"
                trip.status = TripStatus.confirmed
                if trip.external_booking_id:
                    await assign_driver_to_booking(trip.external_booking_id, driver.drivercode)
            elif intent == "no":
                offer.status = OfferStatus.rejected
                offer.ai_interpretation = "no"
                trip.status = TripStatus.open
                refused_trips.append(trip)
            else:
                offer.ai_interpretation = "ambiguous"

        await db.commit()

        if refused_trips:
            farewell = await claude.generate_rejection_followup(driver.name)
            await whatsapp.send_text(driver.phone, farewell)
            for trip in refused_trips:
                await _requeue_trip(trip, batch.id, driver.region if hasattr(driver, 'region') else "", db)

        all_resolved = all(o.status != OfferStatus.pending for o in offers)
        if all_resolved:
            batch.status = BatchStatus.completed
            await db.commit()
            scheduler.remove_job(f"batch_timeout_{batch.id}")
            accepted = [t for o, t in zip(offers, trips) if o.status == OfferStatus.accepted]
            await _notify_michel_summary(driver, accepted, refused_trips, db)

        await _check_restriction_update_for_driver(driver, body, db)


async def _requeue_trip(trip: Trip, exclude_batch_id: int, region: str, db: AsyncSession) -> None:
    """Re-offer a single refused trip to the next best available driver."""
    drivers = await _load_region_drivers(region, db)
    tried_driver_ids = await _get_tried_driver_ids_for_trip(trip.id, db)
    available = [d for d in drivers if d.id not in tried_driver_ids]

    if not available:
        await _notify_michel_unassigned([trip], [], db)
        return

    ranked = await claude.rank_drivers_for_batch([trip], available)
    for entry in ranked:
        driver = await db.get(Driver, entry["driver_id"])
        if driver and not _trips_conflict([trip], []):
            await _send_driver_batch(driver, [trip], db)
            return

    await _notify_michel_unassigned([trip], [], db)


async def _driver_batch_timeout(batch_id: int) -> None:
    async with AsyncSessionLocal() as db:
        batch = await db.get(BatchOffer, batch_id)
        if not batch or batch.status != BatchStatus.pending:
            return
        offers = await _get_batch_offers(batch_id, db)
        timed_out_trips = []
        for offer in offers:
            if offer.status == OfferStatus.pending:
                offer.status = OfferStatus.timeout
                trip = await db.get(Trip, offer.trip_id)
                if trip:
                    trip.status = TripStatus.open
                    timed_out_trips.append(trip)
        batch.status = BatchStatus.timeout
        await db.commit()

        if timed_out_trips and batch.driver:
            timeout_msg = f"הי {batch.driver.name.split()[0]}, לא קיבלנו תשובה בזמן. עברנו הלאה. יום טוב!"
            await whatsapp.send_text(batch.driver.phone, timeout_msg)

        for trip in timed_out_trips:
            driver = await db.get(Driver, batch.driver_id)
            region = driver.region if driver else ""
            await _requeue_trip(trip, batch_id, region, db)


# ─── Supplier batch dispatch ──────────────────────────────────────────────────

async def dispatch_supplier_batch(trip_ids: list[int], supplier_id: int, db: AsyncSession) -> dict:
    """Send all assigned rides to a supplier in one WhatsApp message."""
    trips = await _load_trips(trip_ids, db)
    supplier = await db.get(Supplier, supplier_id)
    if not trips or not supplier:
        return {"sent": False}

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.supplier_offer_timeout_seconds)
    batch = BatchOffer(
        batch_type=BatchType.supplier,
        supplier_id=supplier_id,
        expires_at=expires_at,
    )
    db.add(batch)
    await db.flush()

    for trip in trips:
        offer = Offer(
            trip_id=trip.id,
            supplier_id=supplier_id,
            batch_offer_id=batch.id,
            expires_at=expires_at,
        )
        db.add(offer)
        trip.status = TripStatus.offered

    await db.commit()
    await db.refresh(batch)

    message_body = await _build_supplier_message(supplier, trips)
    wa_id = await whatsapp.send_text(supplier.phone, message_body)
    batch.wa_message_id = wa_id
    await db.commit()

    scheduler.add_job(
        _supplier_batch_timeout,
        trigger="date",
        run_date=expires_at,
        id=f"supplier_batch_{batch.id}",
        kwargs={"batch_id": batch.id},
        replace_existing=True,
        misfire_grace_time=300,
    )
    return {"sent": True, "batch_id": batch.id}


async def handle_supplier_reply(from_phone: str, wa_message_id: str, body: str) -> None:
    async with AsyncSessionLocal() as db:
        supplier = await _find_supplier_by_phone(from_phone, db)
        if not supplier:
            return
        batch = await _get_pending_supplier_batch(supplier.id, db)
        if not batch:
            return

        offers = await _get_batch_offers(batch.id, db)
        trips = {str(t.external_booking_id): (o, t)
                 for o in offers
                 for t in [await db.get(Trip, o.trip_id)]
                 if t}

        parsed = await claude.parse_supplier_reply(body, list(trips.keys()))
        unconfirmed = []

        for booking_id, intent in parsed.items():
            if booking_id in trips:
                offer, trip = trips[booking_id]
                if intent == "confirm":
                    offer.status = OfferStatus.accepted
                    trip.status = TripStatus.confirmed
                elif intent == "decline":
                    offer.status = OfferStatus.rejected
                    trip.status = TripStatus.open
                    unconfirmed.append(trip)

        batch.raw_reply = body
        await db.commit()

        if unconfirmed:
            await _notify_michel_unassigned(unconfirmed, [], db)

        all_resolved = all(o.status != OfferStatus.pending for o in offers)
        if all_resolved:
            batch.status = BatchStatus.completed
            await db.commit()
            scheduler.remove_job(f"supplier_batch_{batch.id}")


async def _supplier_batch_timeout(batch_id: int) -> None:
    async with AsyncSessionLocal() as db:
        batch = await db.get(BatchOffer, batch_id)
        if not batch or batch.status != BatchStatus.pending:
            return
        offers = await _get_batch_offers(batch_id, db)
        unconfirmed = []
        for offer in offers:
            if offer.status == OfferStatus.pending:
                offer.status = OfferStatus.timeout
                trip = await db.get(Trip, offer.trip_id)
                if trip:
                    trip.status = TripStatus.open
                    unconfirmed.append(trip)
        batch.status = BatchStatus.timeout
        await db.commit()
        if unconfirmed:
            await _notify_michel_unassigned(unconfirmed, [], db)


async def _build_supplier_message(supplier: Supplier, trips: list[Trip]) -> str:
    lines = [f"היי {supplier.name}, יש לך {len(trips)} נסיעות לאישור:\n"]
    for i, trip in enumerate(trips, 1):
        link = settings.ride_control_link(trip.external_booking_id or str(trip.id))
        lines.append(
            f"{i}. {trip.pickup_time.strftime('%a %d/%m %H:%M')} | "
            f"{trip.pickup_city} → {trip.dropoff_city} | "
            f"{trip.num_passengers} נוסעים\n"
            f"   אישור: {link}\n"
        )
    lines.append("ענה לכל נסיעה עם מספר ו'מאשר' או 'לא יכול'.")
    return "\n".join(lines)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pack_trips(trips: list[Trip], driver: Driver) -> list[Trip]:
    """Greedy: pick maximal non-conflicting subset from trips list for this driver."""
    packed = []
    for trip in trips:
        if VEHICLE_CAPACITY_OK(trip, driver) and not _trips_conflict([trip], packed):
            packed.append(trip)
    return packed


def VEHICLE_CAPACITY_OK(trip: Trip, driver: Driver) -> bool:
    from app.utils.constraints import vehicle_eligible
    from app.models.driver import VEHICLE_CAPACITY
    return (
        vehicle_eligible(trip.vehicle_type, driver.vehicle_type)
        and VEHICLE_CAPACITY[driver.vehicle_type] >= trip.num_passengers
    )


def _trips_conflict(new_trips: list[Trip], existing: list[Trip]) -> bool:
    all_trips = existing + new_trips
    for i, a in enumerate(all_trips):
        for b in all_trips[i+1:]:
            dur_a = timedelta(minutes=a.estimated_duration_minutes or 90)
            dur_b = timedelta(minutes=b.estimated_duration_minutes or 90)
            if a.pickup_time < b.pickup_time + dur_b and b.pickup_time < a.pickup_time + dur_a:
                return True
    return False


async def _load_trips(trip_ids: list[int], db: AsyncSession) -> list[Trip]:
    result = await db.execute(select(Trip).where(Trip.id.in_(trip_ids)))
    return list(result.scalars().all())


async def _load_region_drivers(region: str, db: AsyncSession) -> list[Driver]:
    result = await db.execute(
        select(Driver).where(Driver.region == region, Driver.active == True)
    )
    return list(result.scalars().all())


async def _get_batch_offers(batch_id: int, db: AsyncSession) -> list[Offer]:
    result = await db.execute(select(Offer).where(Offer.batch_offer_id == batch_id))
    return list(result.scalars().all())


async def _get_tried_driver_ids_for_trip(trip_id: int, db: AsyncSession) -> list[int]:
    result = await db.execute(
        select(Offer.driver_id).where(Offer.trip_id == trip_id, Offer.driver_id.isnot(None))
    )
    return [r[0] for r in result.all()]


async def _get_pending_driver_batch(driver_id: int, db: AsyncSession) -> BatchOffer | None:
    result = await db.execute(
        select(BatchOffer).where(
            BatchOffer.driver_id == driver_id,
            BatchOffer.status == BatchStatus.pending,
            BatchOffer.batch_type == BatchType.driver,
        ).order_by(BatchOffer.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_pending_supplier_batch(supplier_id: int, db: AsyncSession) -> BatchOffer | None:
    result = await db.execute(
        select(BatchOffer).where(
            BatchOffer.supplier_id == supplier_id,
            BatchOffer.status == BatchStatus.pending,
        ).order_by(BatchOffer.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _find_driver_by_phone(phone: str, db: AsyncSession) -> Driver | None:
    from app.services.whatsapp import _normalize_phone
    normalized = _normalize_phone(phone)
    result = await db.execute(select(Driver).where(Driver.phone.contains(normalized[-9:])))
    return result.scalar_one_or_none()


async def _find_supplier_by_phone(phone: str, db: AsyncSession) -> Supplier | None:
    from app.services.whatsapp import _normalize_phone
    normalized = _normalize_phone(phone)
    result = await db.execute(select(Supplier).where(Supplier.phone.contains(normalized[-9:])))
    return result.scalar_one_or_none()


async def _notify_michel_summary(driver: Driver, accepted: list[Trip], refused: list[Trip], db: AsyncSession) -> None:
    lines = [f"סיכום נסיעות — {driver.name}:"]
    for t in accepted:
        lines.append(f"✓ #{t.id} {t.pickup_city}→{t.dropoff_city} {t.pickup_time.strftime('%d/%m %H:%M')}")
    for t in refused:
        lines.append(f"✗ #{t.id} {t.pickup_city}→{t.dropoff_city} — סירב")
    await whatsapp.send_text(settings.michel_phone, "\n".join(lines))


async def _notify_michel_unassigned(trips: list[Trip], tried: list[Driver], db: AsyncSession) -> None:
    lines = [f"⚠️ {len(trips)} נסיעות ללא נהג:"]
    for t in trips:
        lines.append(f"#{t.id} {t.pickup_city}→{t.dropoff_city} {t.pickup_time.strftime('%d/%m %H:%M')}")
    await whatsapp.send_text(settings.michel_phone, "\n".join(lines))


async def _check_restriction_update(phone: str, body: str) -> None:
    async with AsyncSessionLocal() as db:
        driver = await _find_driver_by_phone(phone, db)
        if driver:
            await _check_restriction_update_for_driver(driver, body, db)


async def _check_restriction_update_for_driver(driver: Driver, body: str, db: AsyncSession) -> None:
    from app.services.restriction_parser import extract_restriction_update
    update = await extract_restriction_update(body)
    if update:
        for field, value in update.items():
            if hasattr(driver, field):
                setattr(driver, field, value)
        await db.commit()
