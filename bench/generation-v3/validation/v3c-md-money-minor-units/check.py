import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ledger/minor_units.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

D = mod.Decimal
assert mod.to_minor_units("12.34") == 1234
assert mod.to_minor_units("12.3") == 1230
assert mod.to_minor_units("0.01") == 1
assert mod.to_minor_units("0.00") == 0
assert mod.to_minor_units("-5.00") == -500
assert mod.to_minor_units("500", "JPY") == 500
assert mod.to_minor_units("1.234", "KWD") == 1234
assert mod.to_minor_units(D("7.50")) == 750
# trailing zeros beyond the exponent carry no extra value: allowed
assert mod.to_minor_units("1.230", "USD") == 123
# real excess precision is rejected, never rounded away
for bad, cur in [("1.005", "USD"), ("500.5", "JPY"), ("0.0001", "USD")]:
    try:
        mod.to_minor_units(bad, cur); assert False, bad
    except ValueError: pass
try:
    mod.to_minor_units(1.23); assert False
except TypeError: pass
try:
    mod.to_minor_units("1.00", "XXX"); assert False
except ValueError: pass
assert mod.from_minor_units(1234) == D("12.34")
assert mod.from_minor_units(500, "JPY") == D("500")
assert mod.from_minor_units(mod.to_minor_units("99.99")) == D("99.99")
print("ok")
