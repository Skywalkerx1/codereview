import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ledger/bill_split.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

assert mod.split_bill(100, 3) == [34, 33, 33]
assert mod.split_bill(101, 4) == [26, 25, 25, 25]
assert mod.split_bill(99, 3) == [33, 33, 33]
assert mod.split_bill(0, 5) == [0, 0, 0, 0, 0]
assert mod.split_bill(1, 3) == [1, 0, 0]
assert mod.split_bill(1000, 1) == [1000]
assert mod.split_bill_named(100, ["Ana", "Ben", "Cy"]) == {"Ana": 34, "Ben": 33, "Cy": 33}
try:
    mod.split_bill_named(100, ["Ana", "Ana"]); assert False
except ValueError: pass
for total, n in [(12345, 7), (5, 10), (999, 13)]:
    shares = mod.split_bill(total, n)
    assert sum(shares) == total and len(shares) == n
    assert max(shares) - min(shares) <= 1, shares
for bad in [(-1, 2), (100, 0), (100, -3)]:
    try:
        mod.split_bill(*bad); assert False, bad
    except ValueError: pass
print("ok")
