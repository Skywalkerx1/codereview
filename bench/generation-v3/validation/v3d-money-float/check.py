import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/invoicing.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from decimal import Decimal

# Half-cent cases where binary float sits just below the boundary.
assert mod.invoice_total([("1.005", 1)]) == Decimal("1.01")
assert mod.invoice_total([("2.675", 1)]) == Decimal("2.68")
# Ordinary exact cases still work.
assert mod.invoice_total([("0.10", 1), ("0.20", 1)]) == Decimal("0.30")
assert mod.invoice_total([("19.99", 3)]) == Decimal("59.97")
assert mod.invoice_total_cents([("1.005", 1)]) == 101
assert mod.invoice_total([]) == Decimal("0.00")
print("ok")
