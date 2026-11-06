import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/session_store.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
now = [100.0]
store = mod.SessionStore(60, clock=lambda: now[0])
assert store.get("nope") is None
store.create("s1", "alice"); store.create("s2", "bob")
assert store.get("s1") == "alice" and len(store) == 2
now[0] = 159.9; assert store.get("s1") == "alice"
now[0] = 160.0; assert store.get("s1") is None, "exactly TTL is expired"
assert len(store) == 1, "expired get sweeps that session"
now[0] = 161.0; assert store.sweep() == 1 and len(store) == 0
store.create("s3", "carol"); now[0] = 170.0; store.create("s3", "carol2")
now[0] = 225.0; assert store.get("s3") == "carol2", "re-create refreshes expiry"
print("ok")
