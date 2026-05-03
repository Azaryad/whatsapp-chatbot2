from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum
from app.database import Base


class BatchType(str, enum.Enum):
    driver = "driver"
    supplier = "supplier"


class BatchStatus(str, enum.Enum):
    pending = "pending"      # waiting for replies
    partial = "partial"      # some accepted, some refused/pending
    completed = "completed"  # all rides resolved
    timeout = "timeout"


class BatchOffer(Base):
    __tablename__ = "batch_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_type: Mapped[BatchType] = mapped_column(SAEnum(BatchType), nullable=False)
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.id"), nullable=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[BatchStatus] = mapped_column(SAEnum(BatchStatus), default=BatchStatus.pending)
    wa_message_id: Mapped[str] = mapped_column(String(200), nullable=True)
    raw_reply: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    driver: Mapped["Driver"] = relationship("Driver", foreign_keys=[driver_id])
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="batch_offers")
    offers: Mapped[list["Offer"]] = relationship("Offer", back_populates="batch")
