import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/health_aggregator.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import threading
agg = mod.HealthAggregator()
assert agg.report() == {"status": "ok", "checks": {}}
agg.add("db", lambda: "ok")
agg.add("cache", lambda: "degraded")
rep = agg.report()
assert rep["status"] == "degraded"  # worst of entries
assert rep["checks"]["db"] == {"status": "ok", "detail": ""}
assert rep["checks"]["cache"]["status"] == "degraded"
# A raising check is down, with detail, and dominates the overall
agg2 = mod.HealthAggregator()
agg2.add("fine", lambda: "ok")
def explode():
    raise ConnectionError("refused")
agg2.add("api", explode)
rep = agg2.report()
assert rep["status"] == "down"
assert rep["checks"]["api"]["status"] == "down"
assert "refused" in rep["checks"]["api"]["detail"]
assert rep["checks"]["fine"]["status"] == "ok"
# A hanging check degrades only its own entry; others still report
agg3 = mod.HealthAggregator()
never = threading.Event()
agg3.add("slow", lambda: never.wait() or "ok", timeout=0.1)
agg3.add("fast", lambda: "ok", timeout=1.0)
rep = agg3.report()
assert rep["checks"]["slow"] == {"status": "degraded", "detail": "timeout"}
assert rep["checks"]["fast"]["status"] == "ok"
assert rep["status"] == "degraded"  # hanging check did not make it down
# Unexpected return values are degraded, not silently ok
agg4 = mod.HealthAggregator()
agg4.add("weird", lambda: "green")
assert agg4.report()["checks"]["weird"]["status"] == "degraded"
try:
    agg4.add("weird", lambda: "ok"); assert False
except ValueError:
    pass
print("ok")
