import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/retention_purge.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def row(rid, tenant, status, finished):
    return {"id": rid, "tenant_id": tenant, "status": status,
            "finished_at": finished}

rows = [
    row(1, "tenant-a", "completed", "2026-01-01T00:00:00Z"),
    row(2, "tenant-b", "completed", "2026-01-01T00:00:00Z"),
    row(3, "tenant-a", "running", "2026-01-01T00:00:00Z"),
    row(4, "tenant-a", "completed", "2026-09-01T00:00:00Z"),
    row(5, "tenant-b", "failed", "2025-12-31T00:00:00Z"),
]
removed = mod.purge_old_rows(rows, "tenant-a", "2026-06-01T00:00:00Z")
assert removed == 1, removed
remaining = sorted(r["id"] for r in rows)
assert remaining == [2, 3, 4, 5], remaining
# Purging the other tenant removes exactly its old terminal rows.
removed_b = mod.purge_old_rows(rows, "tenant-b", "2026-06-01T00:00:00Z")
assert removed_b == 2, removed_b
assert sorted(r["id"] for r in rows) == [3, 4]
print("ok")
