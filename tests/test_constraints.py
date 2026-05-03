from datetime import datetime
from app.models.driver import VehicleType
from app.utils.constraints import vehicle_eligible
from app.utils.shabbat import is_shabbat, is_night


def test_vehicle_upgrade_sedan_to_minivan():
    assert vehicle_eligible(VehicleType.sedan, VehicleType.minivan) is True

def test_vehicle_no_downgrade():
    assert vehicle_eligible(VehicleType.minivan, VehicleType.sedan) is False

def test_executive_protected():
    assert vehicle_eligible(VehicleType.executive_minivan, VehicleType.minivan) is False
    assert vehicle_eligible(VehicleType.executive_minivan, VehicleType.sedan) is False
    assert vehicle_eligible(VehicleType.executive_minivan, VehicleType.executive_minivan) is True

def test_shabbat_friday_evening():
    # Friday 19:00
    dt = datetime(2025, 1, 3, 19, 0)  # Jan 3 2025 = Friday
    assert is_shabbat(dt) is True

def test_shabbat_saturday_morning():
    dt = datetime(2025, 1, 4, 10, 0)  # Saturday
    assert is_shabbat(dt) is True

def test_shabbat_saturday_after_end():
    dt = datetime(2025, 1, 4, 20, 0)  # Saturday 20:00 — after 19:30
    assert is_shabbat(dt) is False

def test_not_shabbat_weekday():
    dt = datetime(2025, 1, 6, 10, 0)  # Monday
    assert is_shabbat(dt) is False

def test_night_hour():
    assert is_night(datetime(2025, 1, 1, 23, 0)) is True
    assert is_night(datetime(2025, 1, 1, 3, 0)) is True
    assert is_night(datetime(2025, 1, 1, 10, 0)) is False
