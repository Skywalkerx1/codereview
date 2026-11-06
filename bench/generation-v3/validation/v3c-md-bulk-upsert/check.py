import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("catalog/bulk_upsert.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

store = {}
result = mod.bulk_upsert(store, [
    {"id": 1, "name": "Widget", "price": 100, "stock": 7},
    {"id": 2, "name": "Gadget", "price": 200, "stock": 3},
], update_columns=["price"])
assert result == {"inserted": 2, "updated": 0}
assert store[1] == {"id": 1, "name": "Widget", "price": 100, "stock": 7}
# on conflict ONLY the listed column moves; name/stock keep stored values
result = mod.bulk_upsert(store, [
    {"id": 1, "name": "Renamed", "price": 150, "stock": 0},
], update_columns=["price"])
assert result == {"inserted": 0, "updated": 1}
assert store[1] == {"id": 1, "name": "Widget", "price": 150, "stock": 7}, store[1]
# a listed column missing from the incoming row keeps its stored value
mod.bulk_upsert(store, [{"id": 1, "name": "X"}], update_columns=["price"])
assert store[1]["price"] == 150 and store[1]["name"] == "Widget"
# mixed batch counts inserts and updates separately
result = mod.bulk_upsert(store, [
    {"id": 2, "price": 250}, {"id": 3, "name": "New", "price": 5},
], update_columns=["price"])
assert result == {"inserted": 1, "updated": 1}
assert store[2]["price"] == 250 and store[2]["name"] == "Gadget"
assert store[3] == {"id": 3, "name": "New", "price": 5}
# empty update_columns: conflicts change nothing but still count as updated
result = mod.bulk_upsert(store, [{"id": 3, "price": 999}], update_columns=[])
assert result == {"inserted": 0, "updated": 1} and store[3]["price"] == 5
# inserted rows are copies: mutating the caller's dict does not leak in
row = {"id": 9, "price": 1}
mod.bulk_upsert(store, [row], update_columns=["price"])
row["price"] = 555
assert store[9]["price"] == 1
for rows, cols in [([{"name": "no id"}], ["price"]), ([{"id": 1}], ["id"])]:
    try:
        mod.bulk_upsert({}, rows, cols); assert False, (rows, cols)
    except ValueError: pass
print("ok")
