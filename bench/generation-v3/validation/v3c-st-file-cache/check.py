import hashlib, importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/file_cache.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    c = mod.FileCache(os.path.join(d, "cache"))
    data = b"payload-\x00\xff"
    good = hashlib.sha256(data).hexdigest()
    assert c.get("a.bin") is None
    c.put("a.bin", data, good)
    assert c.get("a.bin") == data and c.exists("a.bin")
    try:
        c.put("b.bin", data, "0" * 64); raise AssertionError("bad checksum must raise")
    except ValueError:
        pass
    assert c.get("b.bin") is None and not c.exists("b.bin")
    assert not [n for n in os.listdir(os.path.join(d, "cache")) if n.endswith(".part")]
    empty = hashlib.sha256(b"").hexdigest()
    c.put("empty", b"", empty); assert c.get("empty") == b""
    for bad_key in ("../x", "a/b", ".."):
        try:
            c.put(bad_key, data, good); raise AssertionError("bad key must raise")
        except ValueError:
            pass
print("ok")
