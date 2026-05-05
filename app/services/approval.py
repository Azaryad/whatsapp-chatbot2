"""
Driver approval tracking.

Flow after a driver says yes on WhatsApp:
  1. Offer moves to status=pending_approval
  2. Approval timeout job fires after 1h (or fast_timeout_seconds)
  3. If offer still pending_approval → mark approval_timeout, suspend trip,
     notify Michel, re-offer to next driver
  4. When the driver clicks an HMAC-signed approval link, our /approve page
     calls handle_driver_approval(offer_id, action, db):
       - approved → offer accepted, trip confirmed, write back to Ride Control
       - declined → offer rejected, trip re-queued

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


async def handle_driver_approval(offer_id: int, action: str, db: AsyncSession) -> tuple[bool, str]:
    """
    Process a driver's click on the approval page.
    action is "approved" or "declined".
    Returns (ok, reason). reason is empty on success, else: not_found / wrong_status / bad_action.
    """
    from app.services.supplier import assign_driver_to_booking, update_booking_notes

    if action not in ("approved", "declined"):
        return False, "bad_action"

    offer = await db.get(Offer, offer_id)
    if not offer:
        return False, "not_found"

    if offer.status not in (OfferStatus.pending, OfferStatus.pending_approval):
        return False, "wrong_status"

    trip = await db.get(Trip, offer.trip_id)
    if not trip:
        return False, "not_found"

    # Cancel any pending approval-timeout job
    job_id = f"approval_check_{offer.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if action == "approved":
        offer.status = OfferStatus.accepted
        trip.status = TripStatus.confirmed
        await db.commit()

        if offer.driver_id:
            driver = await db.get(Driver, offer.driver_id)
            if driver and trip.external_booking_id:
                await assign_driver_to_booking(trip.external_booking_id, driver.drivercode)
                notes = f"Driver: {driver.name} | {driver.phone}"
                await update_booking_notes(trip.external_booking_id, notes)
            if driver:
                await whatsapp.send_text(
                    driver.phone,
                    f"מעולה {driver.name.split()[0]}! הנסיעה אושרה רשמית. תודה!",
                )

    else:  # declined
        offer.status = OfferStatus.rejected
        trip.status = TripStatus.open
        await db.commit()

        name, phone = await _get_contact(offer, db)
        if name and phone:
            await whatsapp.send_text(
                phone,
                f"הי {name.split()[0]}, ראינו שלא אישרת את הנסיעה. מועברת לנהג אחר.",
            )

        if offer.driver_id:
            driver = await db.get(Driver, offer.driver_id)
            region = driver.region if driver else ""
            from app.services.batch_dispatch import _requeue_trip
            await _requeue_trip(trip, offer.batch_offer_id or 0, region, db)

    return True, ""


async def _get_contact(offer: Offer, db: AsyncSession) -> tuple[str, str]:
    if offer.driver_id:
        driver = await db.get(Driver, offer.driver_id)
        return (driver.name, driver.phone) if driver else ("", "")
    if offer.supplier_id:
        supplier = await db.get(Supplier, offer.supplier_id)
        return (supplier.name, supplier.phone) if supplier else ("", "")
    return ("", "")
