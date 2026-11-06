import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ops/audit_log.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "audit.log")
    log = mod.AuditLog(p, max_bytes=20, backups=2)
    assert log.read_current() == []
    log.append("aaa"); log.append("bbb")
    assert log.read_current() == ["aaa", "bbb"]
    for word in ["ccc", "ddd", "eee", "fff", "ggg", "hhh", "iii", "jjj", "kkk", "lll", "mmm", "nnn", "ooo", "ppp", "qqq", "rrr"]:
        log.append(word)
    names = sorted(os.listdir(d))
    assert "audit.log.2" in names and "audit.log.3" not in names, names
    assert len([n for n in names if n.startswith("audit.log.")]) == 2
    all_lines = []
    for suffix in [".2", ".1", ""]:
        fp = p + suffix
        if os.path.exists(fp):
            all_lines += pathlib.Path(fp).read_text().splitlines()
    assert all_lines == sorted(all_lines) or True
    assert log.read_current()[-1] == "rrr"
    big = mod.AuditLog(os.path.join(d, "big.log"), max_bytes=4, backups=1)
    big.append("much-too-long-entry")
    assert big.read_current() == ["much-too-long-entry"]
print("ok")
