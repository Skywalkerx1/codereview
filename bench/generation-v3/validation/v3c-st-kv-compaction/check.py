import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/kv_store.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "kv.log")
    s = mod.KvStore(p)
    assert s.get("x") is None and len(s) == 0
    s.put("a", 1); s.put("b", 2); s.put("a", 3)
    assert s.get("a") == 3 and len(s) == 2
    s.delete("b"); assert s.get("b") is None and len(s) == 1
    assert mod.KvStore(p).get("a") == 3
    s.compact()
    lines = pathlib.Path(p).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and '"a"' in lines[0] and "deleted" not in lines[0]
    assert mod.KvStore(p).get("a") == 3 and len(mod.KvStore(p)) == 1
    s.compact(); assert len(pathlib.Path(p).read_text().strip().splitlines()) == 1
    s.put("键", "值"); s.compact(); assert mod.KvStore(p).get("键") == "值"
print("ok")
