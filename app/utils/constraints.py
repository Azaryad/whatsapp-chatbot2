from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.driver import Driver, VehicleType, VEHICLE_RANK, VEHICLE_CAPACITY
from app.models.trip import Trip
from app.models.offer import Offer, OfferStatus
from app.utils.shabbat import is_shabbat, is_night
from app.services.maps import is_long_distance

EXECUTIVE_TYPES = {VehicleType.executive_minivan}

# Sedan class: cars only — never upgrade to minibus
CAR_CLASS = {VehicleType.sedan, VehicleType.executive_minivan, VehicleType.minivan}
BUS_CLASS = {VehicleType.minibus_15, VehicleType.minibus_18}


def vehicle_eligible(trip_vehicle: VehicleType, driver_vehicle: VehicleType) -> bool:
    """
    Rules:
    - executive_minivan trip → only executive_minivan driver (protected class).
    - sedan trip → car class only (sedan, executive_minivan, minivan). Never minibus.
    - minivan/minibus trip → same rank or higher.
    """
    if trip_vehicle in EXECUTIVE_TYPES:
        return driver_vehicle == trip_vehicle
    if trip_vehicle == VehicleType.sedan and driver_vehicle in BUS_CLASS:
        return False
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
