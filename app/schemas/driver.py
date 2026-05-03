from pydantic import BaseModel, Field
from datetime import datetime
from app.models.driver import VehicleType


class DriverCreate(BaseModel):
    drivercode: str
    name: str
    phone: str
    home_city: str
    vehicle_type: VehicleType
    works_shabbat: bool = False
    works_nights: bool = False
    works_long_distance: bool = False
    languages: str = "Hebrew"
    active: bool = True
    notes: str = ""
    region: str = ""


class DriverRead(DriverCreate):
    id: int
    max_passengers: int
    created_at: datetime

    class Config:
        from_attributes = True


class DriverUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    home_city: str | None = None
    vehicle_type: VehicleType | None = None
    works_shabbat: bool | None = None
    works_nights: bool | None = None
    works_long_distance: bool | None = None
    languages: str | None = None
    active: bool | None = None
    notes: str | None = None
    region: str | None = None
