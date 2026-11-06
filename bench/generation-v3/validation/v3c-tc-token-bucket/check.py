import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/token_bucket.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading
now = [1000.0]
b = mod.TokenBucket(5, 1.0, clock=lambda: now[0])
assert b.available() == 5.0  # initial burst = capacity
assert [b.try_acquire() for _ in range(5)] == [True] * 5
assert b.try_acquire() is False and b.available() == 0.0
now[0] += 2.0  # 2 seconds refill exactly 2 tokens
assert b.available() == 2.0
assert b.try_acquire(2) is True and b.try_acquire() is False
now[0] += 100.0  # refill is capped at capacity, never above
assert b.available() == 5.0
assert b.try_acquire(6) is False  # larger than capacity never succeeds
assert b.available() == 5.0  # failed acquire consumed nothing
try:
    b.try_acquire(0); assert False
except ValueError:
    pass
# Concurrency: 20 threads race for 5 tokens; exactly 5 must win.
now2 = [0.0]
b2 = mod.TokenBucket(5, 0.001, clock=lambda: now2[0])
barrier = threading.Barrier(20); wins = []
def race():
    barrier.wait()
    if b2.try_acquire():
        wins.append(1)
threads = [threading.Thread(target=race) for _ in range(20)]
[t.start() for t in threads]; [t.join() for t in threads]
assert len(wins) == 5, len(wins)
assert b2.available() == 0.0
print("ok")
