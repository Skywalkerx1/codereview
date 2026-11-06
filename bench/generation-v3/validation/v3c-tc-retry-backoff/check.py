import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/retry_helper.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class Transient(Exception): pass
now = [0.0]; sleeps = []
def sleeper(d):
    sleeps.append(d); now[0] += d
# Succeeds on 3rd attempt; delays are jittered halves of 0.1, 0.2
tries = [0]
def flaky():
    tries[0] += 1
    if tries[0] < 3:
        raise Transient("t")
    return "done"
out = mod.retry_call(flaky, max_attempts=3, base_delay=0.1, cap=10.0,
                     retry_exceptions=(Transient,), clock=lambda: now[0],
                     sleeper=sleeper, rand=lambda: 0.5)
assert out == "done" and tries[0] == 3
assert sleeps == [0.05, 0.1], sleeps
# Cap bounds jitter: base grows past cap, delay never exceeds cap
sleeps.clear(); now[0] = 0.0
def always():
    raise Transient("x")
try:
    mod.retry_call(always, max_attempts=5, base_delay=4.0, cap=1.0,
                   retry_exceptions=(Transient,), clock=lambda: now[0],
                   sleeper=sleeper, rand=lambda: 1.0)
    assert False
except Transient:
    pass
assert sleeps == [1.0, 1.0, 1.0, 1.0], sleeps
# Non-transient exception: no retry, no sleep
sleeps.clear(); count = [0]
def fatal():
    count[0] += 1; raise ValueError("fatal")
try:
    mod.retry_call(fatal, retry_exceptions=(Transient,),
                   sleeper=sleeper, rand=lambda: 0.5); assert False
except ValueError:
    pass
assert count[0] == 1 and sleeps == []
# Final failure re-raises the original instance
orig = Transient("original")
def raiser():
    raise orig
try:
    mod.retry_call(raiser, max_attempts=2, retry_exceptions=(Transient,),
                   sleeper=lambda d: None, rand=lambda: 0.0); assert False
except Transient as e:
    assert e is orig
# Deadline stops retrying before the sleep that would cross it
sleeps.clear(); now[0] = 0.0; dcalls = [0]
def dflaky():
    dcalls[0] += 1; raise Transient("d")
try:
    mod.retry_call(dflaky, max_attempts=10, base_delay=1.0, cap=10.0,
                   deadline=0.4, retry_exceptions=(Transient,),
                   clock=lambda: now[0], sleeper=sleeper, rand=lambda: 1.0)
    assert False
except Transient:
    pass
assert dcalls[0] == 1 and sleeps == []  # 1.0s sleep would cross t=0.4
print("ok")
