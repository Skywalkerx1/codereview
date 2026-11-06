import hashlib, importlib.util, pathlib, tempfile
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("transfer/assemble.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def manifest_for(chunks):
    return {i: hashlib.sha256(c).hexdigest() for i, c in enumerate(chunks)}

parts = [b"alpha-", b"beta-", b"gamma"]
manifest = manifest_for(parts)

with tempfile.TemporaryDirectory() as td:
    out = pathlib.Path(td) / "file.bin"
    # out-of-order arrival assembles strictly in index order
    shuffled = [(2, parts[2]), (0, parts[0]), (1, parts[1])]
    n = mod.assemble_chunks(shuffled, manifest, out)
    assert n == len(b"alpha-beta-gamma")
    assert out.read_bytes() == b"alpha-beta-gamma"
    # hash mismatch: no output file is left behind
    bad = pathlib.Path(td) / "bad.bin"
    tampered = [(0, parts[0]), (1, b"XXXX-"), (2, parts[2])]
    try:
        mod.assemble_chunks(tampered, manifest, bad); assert False
    except mod.AssemblyError:
        pass
    assert not bad.exists()
    # failure does not clobber a pre-existing output file
    keep = pathlib.Path(td) / "keep.bin"
    keep.write_bytes(b"original")
    try:
        mod.assemble_chunks(tampered, manifest, keep); assert False
    except mod.AssemblyError:
        pass
    assert keep.read_bytes() == b"original"
    # missing chunk refused, nothing written
    miss = pathlib.Path(td) / "miss.bin"
    try:
        mod.assemble_chunks([(0, parts[0]), (2, parts[2])], manifest, miss)
        assert False
    except mod.AssemblyError:
        pass
    assert not miss.exists()
    # duplicate index refused
    try:
        mod.assemble_chunks(
            [(0, parts[0]), (0, parts[0]), (1, parts[1]), (2, parts[2])],
            manifest, miss)
        assert False
    except mod.AssemblyError:
        pass
    assert not miss.exists()
    # unexpected extra chunk refused
    try:
        mod.assemble_chunks(
            [(i, c) for i, c in enumerate(parts)] + [(3, b"extra")],
            manifest, miss)
        assert False
    except mod.AssemblyError:
        pass
    # gapped manifest itself is refused
    try:
        mod.assemble_chunks([(0, parts[0]), (2, parts[2])],
                            {0: manifest[0], 2: manifest[2]}, miss)
        assert False
    except mod.AssemblyError:
        pass
    # empty assembly writes an empty file and returns 0
    empty = pathlib.Path(td) / "empty.bin"
    assert mod.assemble_chunks([], {}, empty) == 0
    assert empty.read_bytes() == b""
    # no stray .part files remain after success or failure
    leftovers = [p.name for p in pathlib.Path(td).iterdir()
                 if p.name.endswith(".part")]
    assert leftovers == []
print("ok")
