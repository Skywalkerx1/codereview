import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/worker_heartbeat.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "hb")
    hb = mod.WorkerHeartbeat(p, ttl_seconds=15)
    assert hb.status(500.0) == "missing" and hb.age(500.0) is None
    hb.beat(500.0)
    assert hb.status(500.0) == "alive" and hb.age(510.0) == 10.0
    assert hb.status(515.0) == "alive", "exactly TTL is alive"
    assert hb.status(515.001) == "stale"
    hb.beat(600.0); assert hb.status(614.0) == "alive"
    assert not [n for n in os.listdir(d) if n.endswith(".tmp")]
    pathlib.Path(p).write_text("oops", encoding="utf-8")
    try:
        hb.status(600.0); raise AssertionError("corrupt must raise")
    except ValueError:
        pass
print("ok")
