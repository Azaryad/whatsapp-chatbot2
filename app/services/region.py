"""
Derive region from a free-text address using Claude.
Region format: "Country/City" e.g. "Israel/Tel Aviv", "Turkey/Istanbul".
Results are cached in the DB after first lookup.
"""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.region import Region
from app.config import settings

_cache: dict[str, str] = {}


async def get_region_for_address(address: str, db: AsyncSession) -> str:
    """Return region string for a pickup address, creating a Region row if new."""
    key = address.strip().lower()
    if key in _cache:
        return _cache[key]

    region_name = await _ask_claude(address)

    result = await db.execute(select(Region).where(Region.name == region_name))
    if not result.scalar_one_or_none():
        parts = region_name.split("/", 1)
        country = parts[0].strip() if len(parts) == 2 else region_name
        city = parts[1].strip() if len(parts) == 2 else region_name
        db.add(Region(name=region_name, country=country, city=city))
        await db.commit()

    _cache[key] = region_name
    return region_name


async def _ask_claude(address: str) -> str:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=60,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content":
                f'What country and major city does this address belong to?\n"{address}"\n'
                f'Reply ONLY: {{"region": "Country/City"}} — e.g. {{"region": "Israel/Tel Aviv"}} '
                f'or {{"region": "Turkey/Istanbul"}}. Use the most prominent nearby city.'}],
        )
        data = json.loads(response.content[0].text.strip())
        return data["region"]
    except Exception:
        return "Unknown/Unknown"


async def list_regions(db: AsyncSession) -> list[Region]:
    result = await db.execute(select(Region).order_by(Region.country, Region.city))
    return list(result.scalars().all())
