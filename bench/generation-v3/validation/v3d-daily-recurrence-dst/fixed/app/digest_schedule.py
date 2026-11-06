"""Daily 09:00 digest scheduling for the notifications service.

Contract: the digest runs at 09:00 LOCAL time in America/New_York
every calendar day, including across daylight-saving transitions.
The next run is computed by calendar arithmetic — take the local
date, move to the following calendar day, and keep the same local
wall-clock time — never by adding a fixed 24 hours of elapsed
time, which lands an hour late after the spring transition (and
an hour early after the autumn one).
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")
RUN_TIME = time(9, 0)


def next_daily_run(after):
    """Return the next 09:00 local run strictly after ``after``.

    ``after`` is a timezone-aware datetime.  The result is an
    aware datetime in America/New_York whose local time is
    exactly 09:00 on the following calendar day (or today, if
    ``after`` is before today's run).
    """
    local = after.astimezone(ZONE)
    today_run = datetime.combine(local.date(), RUN_TIME, tzinfo=ZONE)
    if local < today_run:
        return today_run
    return datetime.combine(
        local.date() + timedelta(days=1), RUN_TIME, tzinfo=ZONE)
