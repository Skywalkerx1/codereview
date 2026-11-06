import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/job_guard.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    g = mod.JobGuard(os.path.join(d, "lease"), ttl_seconds=30)
    assert g.is_stale(1000.0) is True
    assert g.try_acquire(1000.0) is True
    assert g.try_acquire(1010.0) is False
    assert g.try_acquire(1030.0) is False, "exactly TTL is still held"
    assert g.try_acquire(1030.001) is True
    g.heartbeat(2000.0)
    assert g.is_stale(2030.0) is False and g.is_stale(2030.5) is True
    g.release(); assert g.try_acquire(2001.0) is True
    assert not [n for n in os.listdir(d) if n.endswith(".tmp")]
print("ok")
