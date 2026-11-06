import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/netloc_parse.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Ordinary URLs scope as expected.
assert mod.hostname_of("https://user@example.com:8443/x") == \
    "example.com"
assert mod.hostname_of("https://EXAMPLE.com/") == "example.com"
assert mod.same_site("https://a.example.com/", "https://a.example.com/x")

# U+FF03 FULLWIDTH NUMBER SIGN NFKC-normalizes to '#'. As
# written the netloc is 'example.com\uFF03@bing.com' (host
# bing.com); after normalization the '#' ends the netloc, so
# normalizing consumers see host example.com. The URL is
# ambiguous and must be refused, not silently scoped to the
# wrong host.
try:
    host = mod.hostname_of("https://example.com\uFF03@bing.com/")
    raise AssertionError(f"NFKC-ambiguous netloc accepted: {host}")
except ValueError:
    pass
print("ok")
