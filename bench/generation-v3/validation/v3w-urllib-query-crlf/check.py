import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/request_target.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Ordinary targets build fine.
assert mod.build_request_target("/search", "q=tea") == "/search?q=tea"
assert mod.build_request_target("/plain") == "/plain"
assert mod.request_line("GET", "/a", "b=1") == "GET /a?b=1 HTTP/1.1"

# CRLF in the path is refused.
try:
    mod.build_request_target("/x\r\nInjected: 1")
    raise AssertionError("path CRLF accepted")
except ValueError:
    pass

# CRLF in the QUERY is refused too -- it lands on the same
# request line, so it injects headers just as surely.
try:
    target = mod.build_request_target(
        "/redir", "next=/ok\r\nInjected: pwned")
    raise AssertionError(f"query CRLF accepted: {target!r}")
except ValueError:
    pass
print("ok")
