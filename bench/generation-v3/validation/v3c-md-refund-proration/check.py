import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ledger/refund_proration.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

s = mod.prorate_refund([100, 100, 100], 100)
assert s == [34, 33, 33] and sum(s) == 100, s
s = mod.prorate_refund([1000, 500, 250], 333)
assert sum(s) == 333 and len(s) == 3, s
# exact division leaves nothing to distribute
assert mod.prorate_refund([200, 200], 100) == [50, 50]
# full refund reproduces the lines exactly
assert mod.prorate_refund([123, 456, 789], 1368) == [123, 456, 789]
# zero refund and zero-total edges
assert mod.prorate_refund([10, 20], 0) == [0, 0]
assert mod.prorate_refund([0, 0], 0) == [0, 0]
assert mod.prorate_refund([], 0) == []
# one cent goes to the largest remainder, deterministically
assert mod.prorate_refund([1, 1, 1], 1) == [1, 0, 0]
assert mod.prorate_refund([300, 100], 1) == [1, 0]
# proportional sanity on an uneven split, many random-ish cases sum exact
for amounts, refund in [([7, 13, 29, 101], 77), ([999, 1], 500), ([5], 5)]:
    parts = mod.prorate_refund(amounts, refund)
    assert sum(parts) == refund, (amounts, refund, parts)
for bad in [([100], 101), ([100], -1), ([0, 0], 5), ([-5, 10], 1)]:
    try:
        mod.prorate_refund(*bad); assert False, bad
    except ValueError: pass
print("ok")
