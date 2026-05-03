import openpyxl
from app.schemas.driver import DriverCreate
from app.models.driver import VehicleType


def parse_driver_excel(file_bytes: bytes) -> list[DriverCreate]:
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(file_bytes))
    ws = wb.active

    drivers = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row[0]:
            continue
        drivercode, name, phone, home_city, region, vehicle_type, \
            works_shabbat, works_nights, works_long_distance, \
            languages, active, notes = (row[i] if i < len(row) else None for i in range(12))

        drivers.append(DriverCreate(
            drivercode=str(drivercode).strip(),
            name=str(name).strip(),
            phone=str(phone).strip(),
            home_city=str(home_city).strip(),
            region=str(region or "").strip(),
            vehicle_type=VehicleType(str(vehicle_type).strip()),
            works_shabbat=_parse_bool(works_shabbat),
            works_nights=_parse_bool(works_nights),
            works_long_distance=_parse_bool(works_long_distance),
            languages=str(languages or "Hebrew").strip(),
            active=_parse_bool(active) if active is not None else True,
            notes=str(notes or "").strip(),
        ))
    return drivers


def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().upper() in ("TRUE", "1", "YES", "כן")
    return bool(val)
