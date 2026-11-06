import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/bounded_pool.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading
pool = mod.BoundedPool(num_workers=2, queue_capacity=2)
f = pool.submit(lambda x: x * 2, 21)
assert f.result(timeout=5) == 42
# A failing job surfaces on its Future; the pool keeps working
def boom():
    raise ValueError("bad job")
f2 = pool.submit(boom)
try:
    f2.result(timeout=5); assert False
except ValueError:
    pass
assert pool.submit(lambda: "alive").result(timeout=5) == "alive"
pool.shutdown()
try:
    pool.submit(lambda: 1); assert False
except RuntimeError:
    pass
# Full buffer: block both workers, fill the queue, next submit rejects
pool2 = mod.BoundedPool(num_workers=2, queue_capacity=2)
gate = threading.Event(); started = []
def blocker(i):
    started.append(i); gate.wait(5); return i
futs = [pool2.submit(blocker, i) for i in range(2)]
# Wait deterministically until both workers are inside blocker
import time as _t
deadline = _t.monotonic() + 5
while len(started) < 2 and _t.monotonic() < deadline:
    _t.sleep(0.005)
assert len(started) == 2
queued = [pool2.submit(blocker, i) for i in (2, 3)]  # fills capacity 2
try:
    pool2.submit(blocker, 99); assert False
except mod.PoolFullError:
    pass
gate.set()
pool2.shutdown(wait=True)  # drains every accepted job
assert sorted(f.result(timeout=5) for f in futs + queued) == [0, 1, 2, 3]
# shutdown(wait=False) returns while draining continues; jobs still finish
pool3 = mod.BoundedPool(num_workers=1, queue_capacity=2)
f3 = pool3.submit(lambda: "drained")
pool3.shutdown(wait=False)
assert f3.result(timeout=5) == "drained"
print("ok")
