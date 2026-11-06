import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ledger/invoice_totals.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

D = mod.Decimal
# per-line rounding differs from rounding tax on the subtotal
lines = [{"quantity": 1, "unit_price": "1.05", "tax_rate": "0.0875"}] * 3
r = mod.compute_invoice(lines)
assert r["subtotal"] == D("3.15"), r
assert r["tax"] == D("0.27"), r  # 0.09 per line; on-subtotal would be 0.28
assert r["total"] == D("3.42"), r
# half-up tie: 2.00 * 0.0625 = 0.125 -> 0.13 (half-even would give 0.12)
r = mod.compute_invoice([{"quantity": 1, "unit_price": "2.00", "tax_rate": "0.0625"}])
assert r["tax"] == D("0.13"), r
assert r["total"] == D("2.13"), r
# empty invoice
r = mod.compute_invoice([])
assert r == {"subtotal": D("0.00"), "tax": D("0.00"), "total": D("0.00")}, r
# quantity multiplies before rounding
r = mod.compute_invoice([{"quantity": 3, "unit_price": "3.33", "tax_rate": "0"}])
assert r["subtotal"] == D("9.99") and r["total"] == D("9.99"), r
# floats are rejected, never silently accepted
try:
    mod.compute_invoice([{"quantity": 1, "unit_price": 1.05, "tax_rate": "0.1"}]); assert False
except TypeError: pass
# negative values rejected
try:
    mod.compute_invoice([{"quantity": -1, "unit_price": "1.00", "tax_rate": "0"}]); assert False
except ValueError: pass
# non-numeric and non-finite amounts are ValueError, not decimal crashes
for bad_price in ["abc", "NaN", "Infinity"]:
    try:
        mod.compute_invoice([{"quantity": 1, "unit_price": bad_price, "tax_rate": "0"}]); assert False
    except ValueError: pass
assert isinstance(r["total"], D)
print("ok")
