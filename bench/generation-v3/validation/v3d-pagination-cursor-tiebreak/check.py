import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/feed_pagination.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

rows = [{"id": i, "created_at": "2026-11-01T10:00:00Z"}
        for i in range(1, 6)]
rows += [{"id": 6, "created_at": "2026-11-01T11:00:00Z"},
         {"id": 7, "created_at": "2026-11-01T11:00:00Z"}]
seen, cursor = [], None
for _ in range(10):
    page, cursor = mod.paginate(rows, 2, cursor)
    seen.extend(r["id"] for r in page)
    if cursor is None:
        break
assert seen == [1, 2, 3, 4, 5, 6, 7], seen
assert len(seen) == len(set(seen))
page, nxt = mod.paginate(rows, 10)
assert [r["id"] for r in page] == [1, 2, 3, 4, 5, 6, 7] and nxt is None
page, nxt = mod.paginate([], 5)
assert page == [] and nxt is None
print("ok")
