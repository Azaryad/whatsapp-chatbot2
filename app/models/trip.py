from sqlalchemy import String, Integer, DateTime, Text, Enum as SAEnum, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum
from app.database import Base
from app.models.driver import VehicleType


class TripStatus(str, enum.Enum):
    open = "open"
    offered = "offered"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    unassigned = "unassigned"  # exhausted all drivers


class TripSource(str, enum.Enum):
    booking = "booking"
    website = "website"
    direct = "direct"
    api_push = "api_push"  # pushed from main operating system


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_booking_id: Mapped[str] = mapped_column(String(100), nullable=True, unique=True)
    source: Mapped[TripSource] = mapped_column(SAEnum(TripSource), default=TripSource.api_push)
    pickup_address: Mapped[str] = mapped_column(String(300), nullable=False)
    pickup_city: Mapped[str] = mapped_column(String(100), nullable=False)
    dropoff_address: Mapped[str] = mapped_column(String(300), nullable=False)
    dropoff_city: Mapped[str] = mapped_column(String(100), nullable=False)
    pickup_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    num_passengers: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(SAEnum(VehicleType), nullable=False)
    special_requirements: Mapped[str] = mapped_column(Text, default="")
    price_to_driver: Mapped[float] = mapped_column(Float, nullable=True)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[TripStatus] = mapped_column(SAEnum(TripStatus), default=TripStatus.open)
    region: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    offers: Mapped[list["Offer"]] = relationship("Offer", back_populates="trip")
