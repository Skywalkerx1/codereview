import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/url_guard.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Ordinary URLs split as expected.
assert mod.split_url("http://ok.example/a") == ("http", "ok.example")
assert mod.split_url("https://user@ok.example:8443/x") == \
    ("https", "ok.example")
assert mod.scheme_allowed("https://ok.example/", {"http", "https"})

# A URL starting with blank characters still has its real
# scheme and host (WHATWG: strip leading C0 control / space).
# Parsers that miss this report an empty scheme, so a blocklist
# or allowlist decision is made on the wrong URL.
assert mod.split_url(" http://blocked.example/") == \
    ("http", "blocked.example")
assert mod.split_url("\x01\x02https://blocked.example/") == \
    ("https", "blocked.example")
assert not mod.scheme_allowed(" javascript:alert(1)", {"http", "https"})
print("ok")
