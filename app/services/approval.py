"""
Ride Control approval tracking.

Flow after a driver/supplier says yes on WhatsApp:
  1. Offers move to status=pending_approval
  2. Approval timeout job fires after 1h (or fast_timeout_seconds)
  3. If offer still pending_approval → mark approval_timeout, suspend trip,
     notify Michel, re-offer to next driver
  4. When Ride Control calls POST /api/trips/{id}/rc-confirmed, offer → accepted

This module handles steps 2–4.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.offer import Offer, OfferStatus
from app.models.trip import Trip, TripStatus
from app.models.batch_offer import BatchOffer, BatchStatus
from app.models.driver import Driver
from app.models.supplier import Supplier
from app.services import whatsapp, claude
from app.services.scheduler import scheduler


def schedule_approval_check(offer_id: int) -> None:
    """Schedule a check to verify Ride Control approval was received."""
    run_at = datetime.now(timezone.utc) + timedelta(seconds=settings.approval_timeout_seconds)
    scheduler.add_job(
        _check_approval,
        trigger="date",
        run_date=run_at,
        id=f"approval_check_{offer_id}",
        kwargs={"offer_id": offer_id},
        replace_existing=True,
        misfire_grace_time=300,
    )


async def _check_approval(offer_id: int) -> None:
    async with AsyncSessionLocal() as db:
        offer = await db.get(Offer, offer_id)
        if not offer or offer.status != OfferStatus.pending_approval:
            return

        trip = await db.get(Trip, offer.trip_id)
        offer.status = OfferStatus.approval_timeout
        trip.status = TripStatus.open
        await db.commit()

        # Identify who to warn
        name, phone = await _get_contact(offer, db)
        if name and phone:
            suspended_msg = (
                f"היי {name.split()[0]}, לא קיבלנו אישור דרך המערכת לנסיעה "
                f"{trip.pickup_city}→{trip.dropoff_city}. "
                f"הנסיעה עוברת לנהג אחר."
            )
            await whatsapp.send_text(phone, suspended_msg)

        # Notify Michel
        michel_msg = (
            f"⚠️ אישור לא התקבל — נסיעה #{trip.id} "
            f"{trip.pickup_city}→{trip.dropoff_city} "
            f"{trip.pickup_time.strftime('%d/%m %H:%M')}\n"
            f"{'נהג' if offer.driver_id else 'ספק'}: {name or 'unknown'} אמר כן אבל לא אישר בלינק."
        )
        await whatsapp.send_text(settings.michel_phone, michel_msg)

        # Re-offer the trip
        if offer.driver_id:
            driver = await db.get(Driver, offer.driver_id)
            region = driver.region if driver else ""
            from app.services.batch_dispatch import _requeue_trip
            await _requeue_trip(trip, offer.batch_offer_id or 0, region, db)


async def confirm_ride_control_approval(trip_id: int, db: AsyncSession) -> bool:
    """
    Called when Ride Control sends the approval confirmation (POST /api/trips/{id}/rc-confirmed).
    Moves the offer from pending_approval → accepted.
    """
    result = await db.execute(
        select(Offer).where(
            Offer.trip_id == trip_id,
            Offer.status == OfferStatus.pending_approval,
        ).order_by(Offer.created_at.desc()).limit(1)
    )
    offer = result.scalar_one_or_none()
    if not offer:
        return False

    offer.status = OfferStatus.accepted
    trip = await db.get(Trip, trip_id)
    if trip:
        trip.status = TripStatus.confirmed

    # Cancel the pending approval check
    job_id = f"approval_check_{offer.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    await db.commit()
    return True


async def _get_contact(offer: Offer, db: AsyncSession) -> tuple[str, str]:
    if offer.driver_id:
        driver = await db.get(Driver, offer.driver_id)
        return (driver.name, driver.phone) if driver else ("", "")
    if offer.supplier_id:
        supplier = await db.get(Supplier, offer.supplier_id)
        return (supplier.name, supplier.phone) if supplier else ("", "")
    return ("", "")
