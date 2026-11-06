import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("inventory/csv_import.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

D = mod.Decimal
good = "sku,quantity,unit_price\nA-1,2,9.99\nB-2,5,0.50\n"
store = []
recs = mod.import_csv(good, store)
assert len(recs) == 2 and len(store) == 2
assert recs[0] == {"sku": "A-1", "quantity": 2, "unit_price": D("9.99")}
assert isinstance(recs[1]["quantity"], int) and isinstance(recs[1]["unit_price"], D)
# a bad file commits NOTHING and collects every bad row with its number
bad = "sku,quantity,unit_price\nA-1,2,9.99\nB-2,x,1.00\nC-3,1,nope\nD-4,-2,1.00\n"
store2 = [{"sku": "KEEP", "quantity": 1, "unit_price": D("1.00")}]
try:
    mod.import_csv(bad, store2); assert False
except mod.ImportFailure as exc:
    assert [n for n, _ in exc.errors] == [3, 4, 5], exc.errors
assert store2 == [{"sku": "KEEP", "quantity": 1, "unit_price": D("1.00")}]
# wrong header is row 1 and commits nothing
store3 = []
try:
    mod.import_csv("a,b,c\nX,1,1.00\n", store3); assert False
except mod.ImportFailure as exc:
    assert exc.errors[0][0] == 1
assert store3 == []
# wrong column count and empty sku are reported, not committed
try:
    mod.import_csv("sku,quantity,unit_price\nOnly,Two\n,1,1.00\n", []); assert False
except mod.ImportFailure as exc:
    assert [n for n, _ in exc.errors] == [2, 3], exc.errors
# a NaN price is a collected row error, not a crash or a commit
try:
    mod.import_csv("sku,quantity,unit_price\nA,1,NaN\n", []); assert False
except mod.ImportFailure as exc:
    assert [n for n, _ in exc.errors] == [2], exc.errors
# blank lines are skipped without breaking row numbering of later errors
try:
    mod.import_csv("sku,quantity,unit_price\nA,1,1.00\n\nB,oops,1.00\n", []); assert False
except mod.ImportFailure as exc:
    assert [n for n, _ in exc.errors] == [4], exc.errors
print("ok")
