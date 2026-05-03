from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.driver import Driver, VehicleType, VEHICLE_RANK, VEHICLE_CAPACITY
from app.models.trip import Trip
from app.models.offer import Offer, OfferStatus
from app.utils.shabbat import is_shabbat, is_night
from app.services.maps import is_long_distance

# Vehicle types that carry the "executive" flag — cannot be substituted
EXECUTIVE_TYPES = {VehicleType.executive_minivan}


def vehicle_eligible(trip_vehicle: VehicleType, driver_vehicle: VehicleType) -> bool:
    """
    A driver's vehicle is eligible for a trip if:
    - The trip requires executive: driver must also have an executive vehicle.
    - Otherwise: driver's vehicle rank >= trip's vehicle rank AND capacity covers passengers.
    """
    if trip_vehicle in EXECUTIVE_TYPES:
        return driver_vehicle == trip_vehicle
    return VEHICLE_RANK[driver_vehicle] >= VEHICLE_RANK[trip_vehicle]


async def filter_eligible_drivers(
    trip: Trip,
    db: AsyncSession,
) -> list[Driver]:
    stmt = select(Driver).where(Driver.active == True)
    result = await db.execute(stmt)
    all_drivers: list[Driver] = list(result.scalars().all())

    night = is_night(trip.pickup_time)
    shabbat = is_shabbat(trip.pickup_time)
    long_dist = is_long_distance(trip.distance_km or 0.0)

    eligible = []
    for driver in all_drivers:
        if not vehicle_eligible(trip.vehicle_type, driver.vehicle_type):
            continue
        if VEHICLE_CAPACITY[driver.vehicle_type] < trip.num_passengers:
            continue
        if night and not driver.works_nights:
            continue
        if shabbat and not driver.works_shabbat:
            continue
        if long_dist and not driver.works_long_distance:
            continue
        if not await _no_conflict(driver, trip, db):
            continue
        eligible.append(driver)

    return eligible


async def _no_conflict(driver: Driver, trip: Trip, db: AsyncSession) -> bool:
    """True if the driver has no confirmed trip overlapping with this trip's pickup window."""
    duration = timedelta(minutes=trip.estimated_duration_minutes or 90)
    trip_end = trip.pickup_time + duration

    conflict_stmt = (
        select(Trip)
        .join(Offer, Offer.trip_id == Trip.id)
        .where(
            and_(
                Offer.driver_id == driver.id,
                Offer.status == OfferStatus.accepted,
                Trip.pickup_time < trip_end,
                Trip.pickup_time + timedelta(minutes=90) > trip.pickup_time,
            )
        )
    )
    result = await db.execute(conflict_stmt)
    return result.first() is None
