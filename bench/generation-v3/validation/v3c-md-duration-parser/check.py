import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/duration_parser.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

assert mod.parse_duration("1h30m") == 5400
assert mod.parse_duration("45s") == 45
assert mod.parse_duration("2d") == 172800
assert mod.parse_duration("1w") == 604800
assert mod.parse_duration("1w2d3h4m5s") == 604800 + 172800 + 10800 + 240 + 5
assert mod.parse_duration("0s") == 0
assert mod.parse_duration("90m") == 5400
assert mod.parse_duration(" 1h 30m ") == 5400
assert mod.parse_duration("0h0m") == 0
for bad in ["", "   ", "10", "1x", "1h2h", "-5m", "1.5h", "h", "1hh", "abc", "1H", None]:
    try:
        mod.parse_duration(bad); assert False, repr(bad)
    except ValueError: pass
print("ok")
