import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/config_parser.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

cfg = mod.parse_config("port = 9090\ndebug = true\n", {"port": "8080", "host": "localhost", "debug": "false"})
assert cfg.get_str("host") == "localhost"      # default survives
assert cfg.get_int("port") == 9090             # file overrides default
assert cfg.get_bool("debug") is True           # file overrides default
assert cfg.get_int("missing", 42) == 42        # explicit fallback
try:
    cfg.get_str("missing"); assert False
except KeyError: pass
# typed getters raise on malformed values, never coerce silently
cfg2 = mod.parse_config("workers = three\nflag = maybe\n")
try:
    cfg2.get_int("workers"); assert False
except ValueError: pass
try:
    cfg2.get_bool("flag"); assert False
except ValueError: pass
for token, want in [("yes", True), ("OFF", False), ("0", False), ("On", True)]:
    assert mod.parse_config(f"b = {token}\n").get_bool("b") is want
# duplicate keys: last wins; comments and blanks ignored
cfg3 = mod.parse_config("# note\n\nx = 1\n; other\nx = 2\n")
assert cfg3.get_int("x") == 2
# malformed line names its line number
try:
    mod.parse_config("a = 1\njust words\n"); assert False
except ValueError as exc:
    assert "line 2" in str(exc), exc
print("ok")
