import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/digest_schedule.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

zone = ZoneInfo("America/New_York")
# The morning before spring-forward (2026-03-08) the run has passed.
before_spring = datetime(2026, 3, 7, 10, 0, tzinfo=zone)
nxt = mod.next_daily_run(before_spring)
assert (nxt.month, nxt.day) == (3, 8), nxt
assert (nxt.hour, nxt.minute) == (9, 0), nxt
assert nxt.utcoffset() == timedelta(hours=-4), nxt
# Autumn transition (2026-11-01) likewise stays at 09:00 local.
before_autumn = datetime(2026, 10, 31, 10, 0, tzinfo=zone)
nxt2 = mod.next_daily_run(before_autumn)
assert (nxt2.month, nxt2.day) == (11, 1), nxt2
assert (nxt2.hour, nxt2.minute) == (9, 0), nxt2
assert nxt2.utcoffset() == timedelta(hours=-5), nxt2
# An ordinary day, queried before the run, returns today's 09:00.
morning = datetime(2026, 6, 15, 7, 30, tzinfo=zone)
nxt3 = mod.next_daily_run(morning)
assert (nxt3.day, nxt3.hour) == (15, 9), nxt3
print("ok")
