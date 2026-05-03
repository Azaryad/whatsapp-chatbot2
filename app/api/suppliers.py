from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.schemas.supplier import SupplierCreate, SupplierRead, SupplierUpdate
from app.models.supplier import Supplier

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("/", response_model=list[SupplierRead])
async def list_suppliers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Supplier).order_by(Supplier.name))
    return result.scalars().all()


@router.post("/", response_model=SupplierRead, status_code=201)
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db)):
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.put("/{supplier_id}", response_model=SupplierRead)
async def update_supplier(supplier_id: int, payload: SupplierUpdate, db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(supplier, field, value)
    await db.commit()
    await db.refresh(supplier)
    return supplier
