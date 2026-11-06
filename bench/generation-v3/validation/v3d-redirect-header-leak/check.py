import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/redirect_headers.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

headers = {"Authorization": "Bearer secret-token",
           "Cookie": "session=abc123",
           "Accept": "application/json"}
same = mod.headers_for_redirect(
    headers, "https://api.example.com/a", "https://api.example.com/b")
assert same == headers
cross = mod.headers_for_redirect(
    headers, "https://api.example.com/a", "https://partner.other.net/b")
assert "Authorization" not in cross, cross
assert "Cookie" not in cross, cross
assert cross.get("Accept") == "application/json"
assert headers["Authorization"] == "Bearer secret-token"
print("ok")
