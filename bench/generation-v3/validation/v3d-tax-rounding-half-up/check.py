import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/tax_calc.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from decimal import Decimal

# Exact half-cent: 2.50 * 0.05 = 0.125 -> half-up 0.13 (half-even: 0.12).
assert mod.tax_amount("2.50", "0.05") == Decimal("0.13")
# Another half-cent: 4.50 * 0.05 = 0.225 -> half-up 0.23 (half-even: 0.22).
assert mod.tax_amount("4.50", "0.05") == Decimal("0.23")
# Non-half cases agree under either mode.
assert mod.tax_amount("10.00", "0.07") == Decimal("0.70")
assert mod.tax_amount("19.99", "0.08") == Decimal("1.60")
assert mod.total_with_tax("2.50", "0.05") == Decimal("2.63")
assert mod.tax_amount("0.00", "0.05") == Decimal("0.00")
print("ok")
