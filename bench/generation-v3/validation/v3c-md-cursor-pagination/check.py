import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("feed/pagination.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# many identical timestamps: the id tiebreak must not skip or repeat
items = [{"created_at": "2026-11-05T09:00:00", "id": i} for i in range(10)]
seen, cursor, pages = [], None, 0
while True:
    page, cursor = mod.paginate(items, 3, cursor)
    seen.extend(it["id"] for it in page); pages += 1
    if cursor is None: break
assert seen == list(range(10)), seen
assert pages == 4
# mixed timestamps sort by (created_at, id), input order irrelevant
items = [{"created_at": 2, "id": 1}, {"created_at": 1, "id": 9},
         {"created_at": 1, "id": 3}, {"created_at": 2, "id": 0}]
page, cur = mod.paginate(items, 10)
assert [(it["created_at"], it["id"]) for it in page] == [(1, 3), (1, 9), (2, 0), (2, 1)]
assert cur is None
# exact page boundary: no phantom extra page is needed to finish
page, cur = mod.paginate(items, 4)
assert len(page) == 4 and cur is None
page1, cur1 = mod.paginate(items, 2)
page2, cur2 = mod.paginate(items, 2, cur1)
assert [it["id"] for it in page1 + page2] == [3, 9, 0, 1] and cur2 is None
# empty input, and a cursor at the end, both give an empty last page
assert mod.paginate([], 5) == ([], None)
page, cur = mod.paginate(items, 2, (2, 1))
assert page == [] and cur is None
# input is not mutated
original = list(items)
mod.paginate(items, 2)
assert items == original
try:
    mod.paginate(items, 0); assert False
except ValueError: pass
print("ok")
