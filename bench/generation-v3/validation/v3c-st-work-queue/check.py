import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/work_queue.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    q = mod.WorkQueue(d)
    assert q.claim() is None and q.pending_count() == 0
    q.enqueue("job-b", "second"); q.enqueue("job-a", "first")
    assert q.pending_count() == 2
    first = q.claim(); assert first == "job-a"
    assert q.read_claimed("job-a") == "first"
    second = q.claim(); assert second == "job-b" and second != first
    assert q.claim() is None, "claimed items are not claimable twice"
    assert q.claimed_count() == 2 and q.pending_count() == 0
    q.ack("job-a"); assert q.claimed_count() == 1
    try:
        q.ack("job-a"); raise AssertionError("double ack must raise")
    except FileNotFoundError:
        pass
    try:
        q.enqueue("../evil", "x"); raise AssertionError("traversal must raise")
    except ValueError:
        pass
print("ok")
