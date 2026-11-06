import importlib.util, pathlib, tempfile
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("storage/paths.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as td:
    base = pathlib.Path(td) / "store"
    base.mkdir()
    root = base.resolve()
    # ordinary nested join works, result inside base
    out = mod.join_under_base(base, "a", "b.txt")
    assert out == root / "a" / "b.txt"
    # a fragment carrying its own slash is fine when it stays inside
    assert mod.join_under_base(base, "a/b/c.txt") == root / "a" / "b" / "c.txt"
    # dot and empty components are ignored; base alone is the root
    assert mod.join_under_base(base, ".", "", "x") == root / "x"
    assert mod.join_under_base(base) == root
    # traversal is refused in every spelling
    for bad in ("../secret", "a/../../secret", "..", "a/../.."):
        try:
            mod.join_under_base(base, bad); assert False, bad
        except mod.PathEscapeError:
            pass
    # absolute second argument refused, POSIX and Windows spellings
    for bad in ("/etc/passwd", "\\etc\\passwd", "\\\\host\\share",
                "C:\\Windows\\win.ini", "C:/Windows/win.ini"):
        try:
            mod.join_under_base(base, bad); assert False, bad
        except mod.PathEscapeError:
            pass
    # backslash traversal refused too
    try:
        mod.join_under_base(base, "..\\..\\secret"); assert False
    except mod.PathEscapeError:
        pass
    # backslash as an innocent separator stays inside and is honoured
    assert mod.join_under_base(base, "sub\\dir\\f.txt") == \
        root / "sub" / "dir" / "f.txt"
    # NUL byte refused
    try:
        mod.join_under_base(base, "a\x00b"); assert False
    except mod.PathEscapeError:
        pass
    # a name that merely looks like traversal is fine
    assert mod.join_under_base(base, "..notes.txt") == root / "..notes.txt"
    assert mod.join_under_base(base, ".../ok.txt") == root / "..." / "ok.txt"
print("ok")
