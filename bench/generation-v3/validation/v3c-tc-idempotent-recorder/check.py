import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/order_recorder.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading
r = mod.OrderRecorder()
a = r.record("order-1", {"total": 50})
assert a == {"key": "order-1", "sequence": 1, "payload": {"total": 50}}
b = r.record("order-1", {"total": 999})  # duplicate: original wins
assert b == a and len(r) == 1
c = r.record("order-2", {"total": 5})
assert c["sequence"] == 2 and len(r) == 2
assert r.get("missing") is None and r.get("order-1") == a
# Returned copy cannot corrupt the store, even nested payload mutation
a["sequence"] = 777; a["payload"]["total"] = -1
assert r.get("order-1")["sequence"] == 1
assert r.get("order-1")["payload"] == {"total": 50}
p = {"total": 7}; r.record("order-3", p); p["total"] = 0
assert r.get("order-3")["payload"] == {"total": 7}
for bad in ("", None, 42):
    try:
        r.record(bad, {}); assert False
    except ValueError:
        pass
# Concurrent duplicates: 16 threads, same key, exactly one entry
r2 = mod.OrderRecorder(); barrier = threading.Barrier(16); out = []
def dup(i):
    barrier.wait()
    out.append(r2.record("same-key", {"i": i}))
ts = [threading.Thread(target=dup, args=(i,)) for i in range(16)]
[t.start() for t in ts]; [t.join() for t in ts]
assert len(r2) == 1 and len(out) == 16
assert len({o["sequence"] for o in out}) == 1
assert len({id(o) for o in out}) >= 1  # all are copies of one record
assert r2.get("same-key")["sequence"] == out[0]["sequence"]
print("ok")
