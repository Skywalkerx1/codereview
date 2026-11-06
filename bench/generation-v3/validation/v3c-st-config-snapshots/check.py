import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/config_snapshots.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    s = mod.ConfigSnapshots(os.path.join(d, "snaps"))
    assert s.latest() is None and s.list_versions() == []
    assert s.save({"a": 1}) == 1 and s.save({"a": 2}) == 2
    assert s.latest() == (2, {"a": 2}) and s.get(1) == {"a": 1}
    last = None
    for i in range(3, 9):
        last = s.save({"a": i})
    assert last == 8
    assert s.list_versions() == [4, 5, 6, 7, 8], s.list_versions()
    assert s.get(3) is None and s.get(8) == {"a": 8}
    assert s.latest() == (8, {"a": 8})
    assert len(os.listdir(os.path.join(d, "snaps"))) == 5
    assert mod.ConfigSnapshots(os.path.join(d, "snaps")).save({"a": 9}) == 9
print("ok")
