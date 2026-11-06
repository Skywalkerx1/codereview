import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("netclient/redirects.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def make_transport(routes, seen_requests):
    def transport(req):
        seen_requests.append(req)
        status, location = routes[req.url]
        headers = {"Location": location} if location else {}
        return mod.Response(status, headers, b"body-" + str(status).encode())
    return transport

# same-host redirect preserves Authorization, relative Location resolves
seen = []
routes = {
    "https://api.example.com/start": (302, "/next"),
    "https://api.example.com/next": (200, None),
}
resp = mod.follow_redirects(
    mod.Request("GET", "https://api.example.com/start",
                {"Authorization": "Bearer T", "Accept": "*/*"}),
    make_transport(routes, seen))
assert resp.status == 200
assert seen[1].headers.get("Authorization") == "Bearer T"
assert seen[1].url == "https://api.example.com/next"

# cross-host redirect strips Authorization (any header casing)
seen = []
routes = {
    "https://api.example.com/start": (302, "https://cdn.other.net/file"),
    "https://cdn.other.net/file": (200, None),
}
mod.follow_redirects(
    mod.Request("GET", "https://api.example.com/start",
                {"authorization": "Bearer T"}),
    make_transport(routes, seen))
assert "authorization" not in {k.lower() for k in seen[1].headers}
# host comparison is case-insensitive: EXAMPLE.com -> example.com is same host
seen = []
routes = {
    "https://EXAMPLE.com/a": (301, "https://example.com/b"),
    "https://example.com/b": (200, None),
}
mod.follow_redirects(
    mod.Request("GET", "https://EXAMPLE.com/a", {"Authorization": "Bearer T"}),
    make_transport(routes, seen))
assert seen[1].headers.get("Authorization") == "Bearer T"

# loop A -> B -> A is refused
routes = {
    "https://x.test/a": (302, "https://x.test/b"),
    "https://x.test/b": (302, "https://x.test/a"),
}
try:
    mod.follow_redirects(mod.Request("GET", "https://x.test/a"),
                         make_transport(routes, []))
    assert False, "loop accepted"
except mod.RedirectLoopError:
    pass
# budget: exactly max_redirects succeeds, one more raises
routes = {f"https://x.test/{i}": (302, f"https://x.test/{i+1}")
          for i in range(6)}
routes["https://x.test/6"] = (200, None)
resp = mod.follow_redirects(mod.Request("GET", "https://x.test/0"),
                            make_transport(routes, []), max_redirects=6)
assert resp.status == 200
try:
    mod.follow_redirects(mod.Request("GET", "https://x.test/0"),
                         make_transport(routes, []), max_redirects=5)
    assert False, "budget exceeded silently"
except mod.TooManyRedirectsError:
    pass
# 303 switches POST to GET; 307 keeps the method
seen = []
routes = {"https://x.test/submit": (303, "/done"),
          "https://x.test/done": (200, None)}
mod.follow_redirects(mod.Request("POST", "https://x.test/submit"),
                     make_transport(routes, seen))
assert seen[1].method == "GET"
seen = []
routes = {"https://x.test/a": (307, "/b"), "https://x.test/b": (200, None)}
mod.follow_redirects(mod.Request("POST", "https://x.test/a"),
                     make_transport(routes, seen))
assert seen[1].method == "POST"
# redirect status without Location is returned as-is
resp = mod.follow_redirects(
    mod.Request("GET", "https://x.test/a"),
    make_transport({"https://x.test/a": (302, None)}, []))
assert resp.status == 302
print("ok")
