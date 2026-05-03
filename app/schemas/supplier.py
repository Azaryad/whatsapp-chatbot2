from pydantic import BaseModel
from datetime import datetime


class SupplierCreate(BaseModel):
    supplier_code: str
    name: str
    phone: str
    region: str
    active: bool = True
    notes: str = ""


class SupplierRead(SupplierCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SupplierUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    region: str | None = None
    active: bool | None = None
    notes: str | None = None
