import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/report_entry.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

base = {"provider": "p", "lens": "correctness",
        "status": "error", "attempts": 1}

# Absent key stays absent.
absent = mod.reviewer_report_entry(base)
assert "error_detail" not in absent, absent

# A detail block holding only a fallback_error is persisted.
only_fb = dict(base, error_detail={
    "fallback_error": "HTTP 503 from api.example.com"})
assert mod.reviewer_report_entry(only_fb)["error_detail"] == \
    only_fb["error_detail"]

# A present-but-empty detail block must still be persisted:
# presence, not truthiness, is the contract.
empty = dict(base, error_detail={})
entry = mod.reviewer_report_entry(empty)
assert "error_detail" in entry and entry["error_detail"] == {}, entry
print("ok")
