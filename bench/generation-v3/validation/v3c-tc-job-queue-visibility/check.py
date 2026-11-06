import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/job_queue.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

now = [0.0]
q = mod.JobQueue(clock=lambda: now[0], visibility_timeout=30.0)
assert q.fetch() is None and len(q) == 0
a = q.enqueue("alpha"); b = q.enqueue("beta")
assert (a, b) == (1, 2)
j = q.fetch()
assert (j.id, j.payload, j.deliveries) == (1, "alpha", 1)
j2 = q.fetch()  # alpha is invisible; beta is next
assert (j2.id, j2.payload) == (2, "beta")
assert q.fetch() is None  # both invisible
now[0] = 29.0
assert q.fetch() is None  # timeout not yet elapsed
now[0] = 30.0  # alpha reappears exactly at its deadline, FIFO first
j = q.fetch()
assert (j.id, j.deliveries) == (1, 2)
assert q.ack(1) is True and q.ack(1) is False  # second ack: unknown
now[0] = 1000.0  # acked jobs never reappear; beta does (un-acked)
j = q.fetch()
assert (j.id, j.payload, j.deliveries) == (2, "beta", 2)
assert q.ack(2) is True
now[0] = 2000.0
assert q.fetch() is None and len(q) == 0
assert q.ack(999) is False
print("ok")
