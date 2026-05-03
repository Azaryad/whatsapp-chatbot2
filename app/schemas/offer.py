from pydantic import BaseModel
from datetime import datetime
from app.models.offer import OfferStatus


class OfferRead(BaseModel):
    id: int
    trip_id: int
    driver_id: int
    sent_at: datetime
    expires_at: datetime
    status: OfferStatus
    driver_reply_text: str
    ai_interpretation: str
    rank_position: int
    rank_reason: str
    created_at: datetime

    class Config:
        from_attributes = True


class ManualOverride(BaseModel):
    action: str  # "cancel_offer" | "force_assign" | "mark_handled"
    driver_id: int | None = None
