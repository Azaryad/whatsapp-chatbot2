from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.region import Region
from app.services.region import list_regions

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("/")
async def get_regions(db: AsyncSession = Depends(get_db)):
    regions = await list_regions(db)
    return [{"id": r.id, "name": r.name, "country": r.country, "city": r.city} for r in regions]


@router.post("/", status_code=201)
async def create_region(payload: dict, db: AsyncSession = Depends(get_db)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    parts = name.split("/", 1)
    region = Region(
        name=name,
        country=parts[0].strip() if len(parts) == 2 else name,
        city=parts[1].strip() if len(parts) == 2 else name,
    )
    db.add(region)
    await db.commit()
    await db.refresh(region)
    return {"id": region.id, "name": region.name}


@router.delete("/{region_id}")
async def delete_region(region_id: int, db: AsyncSession = Depends(get_db)):
    region = await db.get(Region, region_id)
    if not region:
        raise HTTPException(status_code=404)
    await db.delete(region)
    await db.commit()
    return {"status": "deleted"}
