import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/lease_manager.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

now = [0.0]
m = mod.LeaseManager(clock=lambda: now[0])
l1 = m.acquire("db", "alice", ttl=10.0)
assert l1 is not None and l1.token == 1 and l1.holder == "alice"
assert m.acquire("db", "bob", ttl=10.0) is None  # held, unexpired
assert m.write("db", l1.token, "v1") is True and m.read("db") == "v1"
assert m.write("db", 999, "evil") is False  # unknown token rejected
assert m.release("db", 999) is False  # wrong token cannot release
now[0] = 10.0  # lease expires exactly at its expiry instant
assert m.write("db", l1.token, "late") is False  # expired: no writes
l2 = m.acquire("db", "bob", ttl=10.0)
assert l2 is not None and l2.token > l1.token  # strictly increasing
# The stale holder is fenced out; the new holder writes fine
assert m.write("db", l1.token, "stale") is False
assert m.read("db") == "v1"
assert m.write("db", l2.token, "v2") is True and m.read("db") == "v2"
assert m.release("db", l1.token) is False  # stale release rejected
assert m.release("db", l2.token) is True
l3 = m.acquire("db", "carol", ttl=5.0)
assert l3.token > l2.token
# Tokens increase across different names too (manager-wide counter)
other = m.acquire("cache", "alice", ttl=5.0)
assert other.token > l3.token
assert m.read("never-written") is None
assert m.write("ghost", other.token, "x") is False  # wrong name/token pair
print("ok")
