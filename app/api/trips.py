from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.schemas.trip import TripIngest, TripRead
from app.schemas.offer import ManualOverride
from app.models.trip import Trip, TripStatus
from app.models.offer import Offer, OfferStatus
from app.services.dispatch import start_dispatch

router = APIRouter(prefix="/api/trips", tags=["trips"])


@router.post("/ingest", response_model=TripRead, status_code=201)
async def ingest_trip(payload: TripIngest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Receive a new trip pushed from the main operating system."""
    if payload.external_booking_id:
        existing = await db.execute(
            select(Trip).where(Trip.external_booking_id == payload.external_booking_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Booking already exists")

    trip = Trip(**payload.model_dump())
    db.add(trip)
    await db.commit()
    await db.refresh(trip)

    background.add_task(start_dispatch, trip.id)
    return trip


@router.get("/", response_model=list[TripRead])
async def list_trips(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trip).order_by(Trip.created_at.desc()))
    return result.scalars().all()


@router.get("/{trip_id}", response_model=TripRead)
async def get_trip(trip_id: int, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404)
    return trip


@router.post("/{trip_id}/override")
async def manual_override(trip_id: int, override: ManualOverride, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404)

    if override.action == "cancel_offer":
        stmt = select(Offer).where(Offer.trip_id == trip_id, Offer.status == OfferStatus.pending)
        result = await db.execute(stmt)
        offer = result.scalar_one_or_none()
        if offer:
            offer.status = OfferStatus.cancelled
            trip.status = TripStatus.open
            await db.commit()
        return {"status": "cancelled"}

    elif override.action == "force_assign":
        if not override.driver_id:
            raise HTTPException(status_code=400, detail="driver_id required")
        from app.models.driver import Driver
        from datetime import datetime, timezone, timedelta
        driver = await db.get(Driver, override.driver_id)
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found")
        offer = Offer(
            trip_id=trip.id,
            driver_id=driver.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=3),
            status=OfferStatus.accepted,
            ai_interpretation="manual",
        )
        db.add(offer)
        trip.status = TripStatus.confirmed
        await db.commit()
        return {"status": "force_assigned"}

    elif override.action == "mark_handled":
        trip.status = TripStatus.completed
        await db.commit()
        return {"status": "marked_handled"}

    raise HTTPException(status_code=400, detail="Unknown action")


@router.post("/{trip_id}/rc-confirmed")
async def ride_control_approved(trip_id: int, db: AsyncSession = Depends(get_db)):
    """
    Called by Ride Control when a driver/supplier clicks the approval link.
    Moves the offer from pending_approval → accepted.
    """
    from app.services.approval import confirm_ride_control_approval
    success = await confirm_ride_control_approval(trip_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="No pending_approval offer found for this trip")
    return {"status": "confirmed"}


@router.post("/batch-dispatch")
async def batch_dispatch_endpoint(
    payload: dict,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Dispatcher sends a set of rides to a region driver queue or a supplier.
    Body: {"trip_ids": [...], "target_type": "driver"|"supplier",
           "region": "...", "supplier_id": ...}
    """
    from app.services.batch_dispatch import dispatch_driver_batch, dispatch_supplier_batch
    trip_ids = payload.get("trip_ids", [])
    target_type = payload.get("target_type")

    if target_type == "driver":
        region = payload.get("region", "")
        background.add_task(dispatch_driver_batch, trip_ids, region, db)
        return {"status": "queued", "target": "driver_region", "region": region}
    elif target_type == "supplier":
        supplier_id = payload.get("supplier_id")
        if not supplier_id:
            raise HTTPException(status_code=400, detail="supplier_id required")
        background.add_task(dispatch_supplier_batch, trip_ids, supplier_id, db)
        return {"status": "queued", "target": "supplier", "supplier_id": supplier_id}
    raise HTTPException(status_code=400, detail="target_type must be 'driver' or 'supplier'")
