import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/debouncer.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

now = [0.0]; timers = []
def fake_schedule(delay, cb):
    entry = {"delay": delay, "cb": cb, "cancelled": False}
    timers.append(entry)
    def cancel():
        entry["cancelled"] = True
    return cancel
d = mod.Debouncer(5.0, 12.0, clock=lambda: now[0], schedule=fake_schedule)
ran = []
d.call(lambda: ran.append("a"))
assert timers[-1]["delay"] == 5.0
now[0] = 4.0
d.call(lambda: ran.append("b"))  # replaces a, reschedules for quiet period
assert timers[0]["cancelled"] is True and timers[-1]["delay"] == 5.0
timers[-1]["cb"]()
assert ran == ["b"]  # only the latest ran, exactly once
# Max-wait: continuous calls every 4s; flush is capped at first+12
timers.clear(); ran.clear(); now[0] = 0.0
d.call(lambda: ran.append(1))
for t in (4.0, 8.0):
    now[0] = t
    d.call(lambda: ran.append(1))
# At t=8 the quiet delay would be 5 but max-wait leaves only 4
assert timers[-1]["delay"] == 4.0, timers[-1]["delay"]
now[0] = 12.0
timers[-1]["cb"]()
assert ran == [1]
# After flush the burst resets: a new call gets the full delay again
now[0] = 20.0
d.call(lambda: ran.append(2))
assert timers[-1]["delay"] == 5.0
# cancel drops without running; flush with nothing pending is a no-op
d.cancel(); d.flush()
assert ran == [1]
print("ok")
