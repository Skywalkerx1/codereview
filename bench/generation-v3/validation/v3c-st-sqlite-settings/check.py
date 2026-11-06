import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/settings_repo.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "s.db")
    r = mod.SettingsRepo(p)
    assert r.journal_mode() == "wal"
    assert r.busy_timeout() == 5000
    assert r.get("nope") is None and r.get("nope", "dflt") == "dflt"
    r.set("theme", "dark"); r.set("theme", "light")
    assert r.get("theme") == "light" and r.count() == 1
    evil = "x'; DROP TABLE settings; --"
    r.set(evil, "v"); assert r.get(evil) == "v" and r.count() == 2
    r.set("unicode-键", "值"); assert r.get("unicode-键") == "值"
    r.delete("theme"); assert r.get("theme") is None
    r.close()
    r2 = mod.SettingsRepo(p); assert r2.get(evil) == "v"; r2.close()
print("ok")
