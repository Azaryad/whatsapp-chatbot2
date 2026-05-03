from sqlalchemy import String, Boolean, Integer, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum
from app.database import Base


class VehicleType(str, enum.Enum):
    sedan = "sedan"                       # up to 4 pax
    executive_minivan = "executive_minivan"  # up to 6 pax, executive class
    minivan = "minivan"                   # up to 7 pax
    minibus_15 = "minibus_15"             # up to 15 pax
    minibus_18 = "minibus_18"             # up to 18 pax


VEHICLE_CAPACITY = {
    VehicleType.sedan: 4,
    VehicleType.executive_minivan: 6,
    VehicleType.minivan: 7,
    VehicleType.minibus_15: 15,
    VehicleType.minibus_18: 18,
}

# Upgrade hierarchy index — higher index = higher class/capacity
VEHICLE_RANK = {
    VehicleType.sedan: 0,
    VehicleType.executive_minivan: 1,
    VehicleType.minivan: 2,
    VehicleType.minibus_15: 3,
    VehicleType.minibus_18: 4,
}


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drivercode: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    home_city: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(SAEnum(VehicleType), nullable=False)
    works_shabbat: Mapped[bool] = mapped_column(Boolean, default=False)
    works_nights: Mapped[bool] = mapped_column(Boolean, default=False)
    works_long_distance: Mapped[bool] = mapped_column(Boolean, default=False)
    languages: Mapped[str] = mapped_column(String(200), default="Hebrew")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    offers: Mapped[list["Offer"]] = relationship("Offer", back_populates="driver")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="driver")

    @property
    def max_passengers(self) -> int:
        return VEHICLE_CAPACITY[self.vehicle_type]
