import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("catalog/price_parser.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

D = mod.Decimal
assert mod.parse_price("1,234.56") == D("1234.56")
assert mod.parse_price("$12.00") == D("12.00")
assert mod.parse_price(" 7.5 ") == D("7.50")
assert mod.parse_price("42") == D("42.00")
assert mod.parse_price("$1,000,000.99") == D("1000000.99")
assert mod.parse_price("0") == D("0.00")
assert mod.parse_price("0.05") == D("0.05")
for bad in ["", "   ", "abc", "1.2.3", "-1.00", "-$5", "$", "12,34.56",
            "1.234", "1,23,456", "$12.00.1", "12a", None, 12, 1.5]:
    try:
        mod.parse_price(bad); assert False, repr(bad)
    except ValueError: pass
print("ok")
