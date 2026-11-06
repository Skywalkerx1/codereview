import importlib.util, json, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/feature_flags.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "flags.json")
    s = mod.FlagStore(p)
    assert s.get("missing") is False
    assert s.all() == {}
    s.set("checkout_v2", True)
    s.set("beta-入口", "on")
    assert s.get("checkout_v2") is True
    assert mod.FlagStore(p).get("beta-入口") == "on"
    s.set("checkout_v2", False)
    assert s.get("checkout_v2") is False and s.get("beta-入口") == "on"
    assert json.loads(pathlib.Path(p).read_text(encoding="utf-8"))["checkout_v2"] is False
    assert not [n for n in os.listdir(d) if n.endswith(".tmp")]
    pathlib.Path(p).write_text("{not json", encoding="utf-8")
    for fn in (lambda: s.get("x"), lambda: s.set("x", 1)):
        try:
            fn(); raise AssertionError("corrupt file must raise")
        except ValueError:
            pass
    assert pathlib.Path(p).read_text(encoding="utf-8") == "{not json"
print("ok")
