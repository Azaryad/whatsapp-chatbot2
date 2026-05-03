from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.schemas.driver import DriverCreate, DriverRead, DriverUpdate
from app.models.driver import Driver
from app.utils.excel_import import parse_driver_excel

router = APIRouter(prefix="/api/drivers", tags=["drivers"])


@router.get("/", response_model=list[DriverRead])
async def list_drivers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Driver).order_by(Driver.name))
    return result.scalars().all()


@router.post("/", response_model=DriverRead, status_code=201)
async def create_driver(payload: DriverCreate, db: AsyncSession = Depends(get_db)):
    driver = Driver(**payload.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.put("/{driver_id}", response_model=DriverRead)
async def update_driver(driver_id: int, payload: DriverUpdate, db: AsyncSession = Depends(get_db)):
    driver = await db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(driver, field, value)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.post("/import", response_model=dict)
async def import_drivers(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload the driver_template.xlsx to bulk-import drivers."""
    contents = await file.read()
    try:
        driver_list = parse_driver_excel(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {e}")

    created, updated = 0, 0
    for d in driver_list:
        existing = await db.execute(select(Driver).where(Driver.drivercode == d.drivercode))
        existing = existing.scalar_one_or_none()
        if existing:
            for field, value in d.model_dump().items():
                setattr(existing, field, value)
            updated += 1
        else:
            db.add(Driver(**d.model_dump()))
            created += 1
    await db.commit()
    return {"created": created, "updated": updated}
