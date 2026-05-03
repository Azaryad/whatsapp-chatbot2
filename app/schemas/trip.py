from pydantic import BaseModel
from datetime import datetime
from app.models.driver import VehicleType
from app.models.trip import TripStatus, TripSource


class TripIngest(BaseModel):
    """Payload pushed from the main operating system."""
    external_booking_id: str | None = None
    source: TripSource = TripSource.api_push
    pickup_address: str
    pickup_city: str
    dropoff_address: str
    dropoff_city: str
    pickup_time: datetime
    num_passengers: int
    vehicle_type: VehicleType
    special_requirements: str = ""
    price_to_driver: float | None = None
    region: str = ""


class TripRead(BaseModel):
    id: int
    external_booking_id: str | None
    source: TripSource
    pickup_address: str
    pickup_city: str
    dropoff_address: str
    dropoff_city: str
    pickup_time: datetime
    num_passengers: int
    vehicle_type: VehicleType
    special_requirements: str
    price_to_driver: float | None
    estimated_duration_minutes: int | None
    distance_km: float | None
    status: TripStatus
    region: str
    created_at: datetime

    class Config:
        from_attributes = True
