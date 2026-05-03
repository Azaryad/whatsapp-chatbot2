from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.trip import Trip, TripStatus
from app.models.offer import Offer
from app.models.driver import Driver
from app.models.message import Message

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    counts = {}
    for status in TripStatus:
        result = await db.execute(select(func.count()).where(Trip.status == status))
        counts[status.value] = result.scalar()
    return {"trip_counts": counts}


@router.get("/active_trips")
async def active_trips(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Trip)
        .where(Trip.status.in_([TripStatus.open, TripStatus.offered, TripStatus.confirmed]))
        .order_by(Trip.pickup_time)
    )
    result = await db.execute(stmt)
    trips = result.scalars().all()

    output = []
    for trip in trips:
        offers_stmt = (
            select(Offer, Driver)
            .join(Driver, Driver.id == Offer.driver_id)
            .where(Offer.trip_id == trip.id)
            .order_by(Offer.created_at)
        )
        offers_result = await db.execute(offers_stmt)
        offer_rows = offers_result.all()

        output.append({
            "trip": {
                "id": trip.id,
                "external_booking_id": trip.external_booking_id,
                "pickup_city": trip.pickup_city,
                "dropoff_city": trip.dropoff_city,
                "pickup_time": trip.pickup_time.isoformat(),
                "num_passengers": trip.num_passengers,
                "vehicle_type": trip.vehicle_type,
                "status": trip.status,
                "price_to_driver": trip.price_to_driver,
            },
            "offers": [
                {
                    "offer_id": o.id,
                    "driver_name": d.name,
                    "driver_phone": d.phone,
                    "vehicle_type": d.vehicle_type,
                    "status": o.status,
                    "sent_at": o.sent_at.isoformat(),
                    "expires_at": o.expires_at.isoformat(),
                    "reply": o.driver_reply_text,
                    "ai_intent": o.ai_interpretation,
                    "rank_reason": o.rank_reason,
                }
                for o, d in offer_rows
            ],
        })
    return output


@router.get("/drivers")
async def driver_activity(db: AsyncSession = Depends(get_db)):
    stmt = select(Driver).order_by(Driver.name)
    result = await db.execute(stmt)
    drivers = result.scalars().all()

    output = []
    for d in drivers:
        last_offer_stmt = (
            select(Offer)
            .where(Offer.driver_id == d.id)
            .order_by(Offer.created_at.desc())
            .limit(1)
        )
        last_offer = (await db.execute(last_offer_stmt)).scalar_one_or_none()
        output.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "home_city": d.home_city,
            "vehicle_type": d.vehicle_type,
            "active": d.active,
            "last_offer_status": last_offer.status if last_offer else None,
            "last_offer_at": last_offer.created_at.isoformat() if last_offer else None,
        })
    return output
