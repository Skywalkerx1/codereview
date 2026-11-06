import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("admin/batch_delete.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def fresh():
    return {i: {"tenant": "acme" if i < 3 else "globex", "v": i} for i in range(5)}
# unfiltered runs refuse and delete nothing
store = fresh()
for kwargs in [{}, {"tenant": None}, {"tenant": "  "}]:
    try:
        mod.batch_delete(store, **kwargs); assert False, kwargs
    except ValueError: pass
assert len(store) == 5
# dry-run reports the count and deletes nothing
store = fresh()
result = mod.batch_delete(store, tenant="acme", dry_run=True)
assert result == {"matched": 3, "deleted": 0} and len(store) == 5
# a real run deletes only the tenant's records
result = mod.batch_delete(store, tenant="acme")
assert result == {"matched": 3, "deleted": 3}
assert sorted(r["tenant"] for r in store.values()) == ["globex", "globex"]
# exceeding the cap refuses and deletes nothing; exactly at cap works
store = fresh()
try:
    mod.batch_delete(store, tenant="acme", max_rows=2); assert False
except ValueError: pass
assert len(store) == 5
result = mod.batch_delete(store, tenant="acme", max_rows=3)
assert result["deleted"] == 3
# an unknown tenant matches zero and is not an error
store = fresh()
assert mod.batch_delete(store, tenant="nope") == {"matched": 0, "deleted": 0}
assert len(store) == 5
print("ok")
