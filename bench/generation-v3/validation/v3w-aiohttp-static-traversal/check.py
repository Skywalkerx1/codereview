import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/static_resolve.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

ROOT = "/srv/static"

# Ordinary files resolve under the root in both modes.
assert mod.resolve_static(ROOT, "css/site.css") == \
    "/srv/static/css/site.css"
assert mod.resolve_static(ROOT, "css/site.css", True) == \
    "/srv/static/css/site.css"

# Traversal is refused with follow_symlinks off.
try:
    mod.resolve_static(ROOT, "../secret.txt")
    raise AssertionError("traversal accepted (default mode)")
except ValueError:
    pass

# Traversal must ALSO be refused with follow_symlinks on: the
# option is about symlinks on disk, and this path contains no
# symlink at all -- it escapes by construction.
try:
    escaped = mod.resolve_static(ROOT, "../secret.txt", True)
    raise AssertionError(f"traversal accepted: {escaped}")
except ValueError:
    pass
try:
    escaped = mod.resolve_static(ROOT, "a/../../secret.txt", True)
    raise AssertionError(f"traversal accepted: {escaped}")
except ValueError:
    pass
print("ok")
