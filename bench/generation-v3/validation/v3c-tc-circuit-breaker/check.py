import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/circuit_breaker.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading
now = [0.0]
cb = mod.CircuitBreaker(failure_threshold=3, cooldown=10.0, clock=lambda: now[0])
def fail():
    raise RuntimeError("down")
def ok():
    return "fine"
assert cb.state == "closed" and cb.call(ok) == "fine"
# Two failures, a success resets the count, then 3 consecutive open it
for fn in (fail, fail):
    try: cb.call(fn); assert False
    except RuntimeError: pass
assert cb.call(ok) == "fine" and cb.state == "closed"
for _ in range(3):
    try: cb.call(fail); assert False
    except RuntimeError: pass
assert cb.state == "open"
# Open: fn is not invoked at all
invoked = [0]
def counted():
    invoked[0] += 1; return 1
try: cb.call(counted); assert False
except mod.CircuitOpenError: pass
assert invoked[0] == 0
now[0] += 9.0  # still inside cooldown
try: cb.call(counted); assert False
except mod.CircuitOpenError: pass
now[0] += 1.0  # cooldown elapsed: exactly one probe admitted
assert cb.state == "half_open"
# While the probe runs, a concurrent call is rejected fast
probe_started = threading.Event(); release = threading.Event(); outcome = []
def probe():
    probe_started.set(); release.wait(5); return "probe-ok"
t = threading.Thread(target=lambda: outcome.append(cb.call(probe)))
t.start(); assert probe_started.wait(5)
try: cb.call(counted); assert False
except mod.CircuitOpenError: pass
assert invoked[0] == 0
release.set(); t.join()
assert outcome == ["probe-ok"] and cb.state == "closed"
# Probe failure re-opens and restarts the cooldown
for _ in range(3):
    try: cb.call(fail); assert False
    except RuntimeError: pass
now[0] += 10.0
try: cb.call(fail); assert False
except RuntimeError: pass
assert cb.state == "open"
now[0] += 9.0
try: cb.call(counted); assert False
except mod.CircuitOpenError: pass
print("ok")
