from __future__ import annotations

from datetime import date, datetime, time, timedelta

SCHEDULE_TIME = time(9, 10)
RETRY_TIMES = (time(9, 40), time(10, 40), time(14, 10))


def _date_range(start: date, end: date) -> tuple[str, ...]:
    if start > end:
        return ()
    return tuple(
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    )


def scheduled_business_dates(
    last_successful_business_date: str | None,
    local_now: datetime,
    *,
    holidays: set[date] | None = None,
) -> tuple[str, ...]:
    """Return the natural dates due for a weekday 09:10 discovery run."""
    today = local_now.date()
    if today.weekday() >= 5 or today in (holidays or set()):
        return ()
    if local_now.time().replace(tzinfo=None) < SCHEDULE_TIME:
        return ()
    end = today - timedelta(days=1)
    if last_successful_business_date:
        start = date.fromisoformat(last_successful_business_date) + timedelta(days=1)
    elif today.weekday() == 0:
        start = today - timedelta(days=3)
    else:
        start = end
    return _date_range(start, end)


def automatic_retry_times(local_day: date) -> tuple[datetime, ...]:
    return tuple(datetime.combine(local_day, item) for item in RETRY_TIMES)
