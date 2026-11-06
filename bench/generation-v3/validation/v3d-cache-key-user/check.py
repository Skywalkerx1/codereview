import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/document_cache.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

calls = []
def loader(user_id, resource_id):
    calls.append((user_id, resource_id))
    return f"private-doc-of-{user_id}"

cache = {}
first = mod.get_document(cache, "user-1", "doc-9", loader)
second = mod.get_document(cache, "user-2", "doc-9", loader)
assert first == "private-doc-of-user-1"
assert second == "private-doc-of-user-2", second
assert calls == [("user-1", "doc-9"), ("user-2", "doc-9")], calls
# A repeat request by the same user is a cache hit.
again = mod.get_document(cache, "user-1", "doc-9", loader)
assert again == first and len(calls) == 2
assert mod.cache_key("user-1", "doc-9") != mod.cache_key("user-2", "doc-9")
print("ok")
