from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum
from app.database import Base


class MessageDirection(str, enum.Enum):
    inbound = "in"
    outbound = "out"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.id"), nullable=False)
    direction: Mapped[MessageDirection] = mapped_column(SAEnum(MessageDirection), nullable=False)
    wa_message_id: Mapped[str] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    related_offer_id: Mapped[int] = mapped_column(Integer, ForeignKey("offers.id"), nullable=True)

    driver: Mapped["Driver"] = relationship("Driver", back_populates="messages")
    offer: Mapped["Offer"] = relationship("Offer", back_populates="messages")
