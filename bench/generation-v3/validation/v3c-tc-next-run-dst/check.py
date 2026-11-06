import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/schedule_next.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
NY = ZoneInfo("America/New_York")
nr = mod.next_run
# Ordinary day: before 09:30 -> same day 09:30 EDT
r = nr(datetime(2025, 6, 1, 8, 0, tzinfo=NY))
assert (r.hour, r.minute) == (9, 30) and r.date().isoformat() == "2025-06-01", r
# After 09:30 -> next day
r = nr(datetime(2025, 6, 1, 10, 0, tzinfo=NY))
assert r.date().isoformat() == "2025-06-02" and (r.hour, r.minute) == (9, 30), r
# Exactly at 09:30 is not strictly after -> next day
r = nr(datetime(2025, 6, 1, 9, 30, tzinfo=NY))
assert r.date().isoformat() == "2025-06-02", r
# Spring forward 2025-03-09: 02:30 does not exist -> shifts to 03:30 EDT
r = nr(datetime(2025, 3, 8, 12, 0, tzinfo=NY), wall_time=time(2, 30))
assert r.date().isoformat() == "2025-03-09" and (r.hour, r.minute) == (3, 30), r
assert r.utcoffset().total_seconds() == -4 * 3600, r
# The daily 09:30 itself is unaffected by the spring-forward day
r = nr(datetime(2025, 3, 9, 8, 0, tzinfo=NY))
assert (r.hour, r.minute) == (9, 30) and r.utcoffset().total_seconds() == -4 * 3600, r
# Fall back 2025-11-02: 01:30 is ambiguous -> earlier (fold=0, EDT) chosen
r = nr(datetime(2025, 11, 1, 12, 0, tzinfo=NY), wall_time=time(1, 30))
assert r.date().isoformat() == "2025-11-02" and r.fold == 0, r
assert r.utcoffset().total_seconds() == -4 * 3600, r
# 09:30 on fall-back day uses the new standard offset
r = nr(datetime(2025, 11, 2, 8, 0, tzinfo=NY))
assert (r.hour, r.minute) == (9, 30) and r.utcoffset().total_seconds() == -5 * 3600, r
# Input in UTC is converted correctly
r = nr(datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc))
assert (r.hour, r.minute) == (9, 30) and r.date().isoformat() == "2025-06-01", r
# Naive input is rejected
try:
    nr(datetime(2025, 6, 1, 8, 0)); assert False, "naive accepted"
except ValueError:
    pass
print("ok")
