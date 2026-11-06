import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/singleflight.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading

# Deterministic concurrency harness: patch threading.Event (looked up by
# the module at call time) with a counting subclass, so the main thread
# knows the exact moment every follower is blocked inside do() waiting
# for the leader -- no sleeps, no timing assumptions. Thread objects are
# created BEFORE patching so their internal events stay real.
real_event = threading.Event
state = {"waiting": 0, "expected": 0}
count_lock = threading.Lock()
all_waiting = real_event()


class CountingEvent(real_event):
    def wait(self, timeout=None):
        with count_lock:
            state["waiting"] += 1
            if state["waiting"] == state["expected"]:
                all_waiting.set()
        return super().wait(timeout)


def concurrent_phase(sf, key, fn, n=8):
    """Run n concurrent do(key, fn) calls; return (results, errors, calls)."""
    results, errors = [], []
    release = real_event()
    calls = [0]

    def leader_fn():
        calls[0] += 1
        release.wait()
        return fn()

    def worker():
        try:
            results.append(sf.do(key, leader_fn))
        except BaseException as exc:  # collected for assertions below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    state["waiting"] = 0
    state["expected"] = n - 1
    all_waiting.clear()
    threading.Event = CountingEvent
    try:
        for t in threads:
            t.start()
        assert all_waiting.wait(10), "followers never all joined the call"
        # Every follower is blocked and the leader is still inside fn:
        # exactly one execution can have started.
        assert calls[0] == 1, calls
        release.set()
        for t in threads:
            t.join(10)
    finally:
        threading.Event = real_event
    assert not any(t.is_alive() for t in threads)
    return results, errors, calls[0]


sf = mod.SingleFlight()

# N concurrent same-key calls: fn executes exactly once, all share it
results, errors, calls = concurrent_phase(sf, "k", lambda: 42)
assert errors == [], errors
assert calls == 1, calls
assert results == [42] * 8, results

# Different keys execute independently
seen = []
def mk(v):
    return lambda: seen.append(v) or v
assert sf.do("a", mk(1)) == 1 and sf.do("b", mk(2)) == 2 and seen == [1, 2]

# A later call re-executes (success is not cached beyond the flight)
assert sf.do("a", mk(3)) == 3

# Concurrent exception: every caller sees it, exactly one execution
def bad():
    raise RuntimeError("boom")
results, errors, calls = concurrent_phase(sf, "e", bad)
assert results == [], results
assert calls == 1, calls
assert len(errors) == 8 and all(isinstance(e, RuntimeError) for e in errors)
assert all(str(e) == "boom" for e in errors)

# The exception was not cached: the next call retries and can succeed
assert sf.do("e", lambda: "recovered") == "recovered"
retry_calls = [0]
def bad2():
    retry_calls[0] += 1
    raise RuntimeError("again")
for _ in range(2):
    try:
        sf.do("x", bad2)
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
assert retry_calls[0] == 2  # retried each time, never cached
print("ok")
