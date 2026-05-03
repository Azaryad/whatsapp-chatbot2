from datetime import datetime, time


SHABBAT_START = time(18, 0)   # Friday 18:00
SHABBAT_END = time(19, 30)    # Saturday 19:30
NIGHT_START = time(22, 0)
NIGHT_END = time(6, 0)


def is_shabbat(dt: datetime) -> bool:
    """Return True if dt falls within Shabbat (Friday 18:00 – Saturday 19:30)."""
    weekday = dt.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    t = dt.time()
    if weekday == 4 and t >= SHABBAT_START:   # Friday evening
        return True
    if weekday == 5 and t <= SHABBAT_END:     # Saturday until end
        return True
    return False


def is_night(dt: datetime) -> bool:
    """Return True if dt falls between 22:00 and 06:00."""
    t = dt.time()
    return t >= NIGHT_START or t < NIGHT_END
