from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum
from app.database import Base


class OfferStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    timeout = "timeout"
    cancelled = "cancelled"


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.id"), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[OfferStatus] = mapped_column(SAEnum(OfferStatus), default=OfferStatus.pending)
    driver_reply_text: Mapped[str] = mapped_column(Text, default="")
    ai_interpretation: Mapped[str] = mapped_column(String(50), default="")
    rank_position: Mapped[int] = mapped_column(Integer, default=0)
    rank_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    trip: Mapped["Trip"] = relationship("Trip", back_populates="offers")
    driver: Mapped["Driver"] = relationship("Driver", back_populates="offers")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="offer")
