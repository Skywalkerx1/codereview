import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/ttl_cache.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

now = [0.0]
c = mod.TTLCache(clock=lambda: now[0], ttl=60.0, grace=30.0)
assert c.lookup("k") is None
c.put("k", "v1")
assert c.lookup("k") == ("v1", False)
now[0] = 59.9
assert c.lookup("k") == ("v1", False)
now[0] = 60.0  # exactly at ttl: stale, never fresh
assert c.lookup("k") == ("v1", True)
now[0] = 89.9
assert c.lookup("k") == ("v1", True)
now[0] = 90.0  # exactly at ttl+grace: miss, and evicted
assert c.lookup("k") is None and len(c) == 0
# Overwriting refreshes the timestamp
c.put("x", 1); now[0] = 100.0; c.put("x", 2)
now[0] = 150.0
assert c.lookup("x") == (2, False)
c.invalidate("x")
assert c.lookup("x") is None
c.invalidate("x")  # invalidating a missing key is a no-op
# Zero grace: an entry goes straight from fresh to miss
c2 = mod.TTLCache(clock=lambda: now[0], ttl=10.0, grace=0.0)
now[0] = 200.0; c2.put("a", "A")
now[0] = 209.9
assert c2.lookup("a") == ("A", False)
now[0] = 210.0
assert c2.lookup("a") is None
# Stored falsy values are still hits, not misses
c2.put("zero", 0)
assert c2.lookup("zero") == (0, False)
print("ok")
