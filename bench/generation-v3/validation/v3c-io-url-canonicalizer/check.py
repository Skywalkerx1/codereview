import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("dedup/canonurl.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
c = mod.canonicalize_url

# scheme/host lowercased, default port dropped, fragment dropped
assert c("HTTP://Example.COM:80/Path?b=2&a=1#frag") == \
    "http://example.com/Path?a=1&b=2"
assert c("https://Example.com:443/x") == "https://example.com/x"
# non-default ports are kept
assert c("http://example.com:8080/x") == "http://example.com:8080/x"
assert c("https://example.com:80/x") == "https://example.com:80/x"
# path case preserved exactly
assert c("http://example.com/Case/Sensitive.TXT") == \
    "http://example.com/Case/Sensitive.TXT"
# query sorted by name then value; duplicates kept, blanks kept
assert c("http://h.test/p?b=2&b=1&a=") == "http://h.test/p?a=&b=1&b=2"
assert c("http://h.test/p?z=9&z=1&z=5") == "http://h.test/p?z=1&z=5&z=9"
# fragment-only difference dedups; empty path becomes /
assert c("http://h.test") == "http://h.test/"
assert c("http://h.test/#section") == "http://h.test/"
assert c("http://h.test/a#one") == c("http://h.test/a#two")
# no query string stays queryless
assert c("http://h.test/plain") == "http://h.test/plain"
# equivalent spellings collapse to one canonical form
assert c("HTTP://EXAMPLE.com:80/A?b=2&b=1") == \
    c("http://example.com/A?b=1&b=2")
# unsupported scheme / missing host / missing scheme raise
for bad in ("ftp://example.com/x", "example.com/no-scheme",
            "http:///path-only", "mailto:a@example.com"):
    try:
        c(bad); assert False, bad
    except ValueError:
        pass
# query values are decoded then re-encoded consistently
assert c("http://h.test/p?q=a%20b") == c("http://h.test/p?q=a+b")
print("ok")
