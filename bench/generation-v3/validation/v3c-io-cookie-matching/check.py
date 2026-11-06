import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("webstate/cookies.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
C = mod.Cookie

host_only = C("sid", "1", "example.com", host_only=True)
domain_c = C("pref", "2", "example.com", host_only=False)

# host-only cookie: exact host only, never subdomains or parent tricks
assert mod.cookie_matches(host_only, "https://example.com/")
assert not mod.cookie_matches(host_only, "https://api.example.com/")
assert not mod.cookie_matches(host_only, "https://badexample.com/")
# domain cookie: domain + subdomains, dot-boundary only
assert mod.cookie_matches(domain_c, "https://example.com/")
assert mod.cookie_matches(domain_c, "https://api.example.com/deep")
assert mod.cookie_matches(domain_c, "https://a.b.example.com/")
assert not mod.cookie_matches(domain_c, "https://badexample.com/")
assert not mod.cookie_matches(domain_c, "https://example.com.evil.test/")
assert not mod.cookie_matches(domain_c, "https://notexample.com/")
# subdomain cookie is not sent up to the parent
sub = C("s", "3", "api.example.com", host_only=False)
assert mod.cookie_matches(sub, "https://api.example.com/")
assert mod.cookie_matches(sub, "https://v2.api.example.com/")
assert not mod.cookie_matches(sub, "https://example.com/")
# host comparison is case-insensitive
assert mod.cookie_matches(host_only, "https://EXAMPLE.COM/")
# path scoping: /app matches /app and /app/x but not /apple
scoped = C("a", "4", "example.com", host_only=True, path="/app")
assert mod.cookie_matches(scoped, "https://example.com/app")
assert mod.cookie_matches(scoped, "https://example.com/app/x")
assert not mod.cookie_matches(scoped, "https://example.com/apple")
assert not mod.cookie_matches(scoped, "https://example.com/other")
# root path matches everything; empty request path counts as /
root = C("r", "5", "example.com", host_only=True, path="/")
assert mod.cookie_matches(root, "https://example.com/anything/deep")
assert mod.cookie_matches(root, "https://example.com")
# selection helper keeps order and drops non-matches
picked = mod.cookies_for_url([host_only, domain_c, scoped],
                             "https://example.com/app/x")
assert [c.name for c in picked] == ["sid", "pref", "a"]
picked = mod.cookies_for_url([host_only, domain_c],
                             "https://api.example.com/")
assert [c.name for c in picked] == ["pref"]
print("ok")
