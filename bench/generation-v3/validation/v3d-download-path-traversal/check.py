import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/download_paths.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

from pathlib import Path

root = Path("downloads")
ok = mod.resolve_download(root, "report-2026.pdf")
assert ok == (root.resolve() / "report-2026.pdf"), ok
nested = mod.resolve_download(root, "2026/q3/report.pdf")
assert nested == (root.resolve() / "2026/q3/report.pdf"), nested
for bad in ("../secret.txt", "../../etc/passwd",
            "2026/../../secret.txt", "/etc/passwd"):
    try:
        mod.resolve_download(root, bad)
        raise AssertionError(f"traversal accepted: {bad}")
    except ValueError:
        pass
    assert mod.is_servable(root, bad) is False
assert mod.is_servable(root, "report-2026.pdf") is True
print("ok")
