import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/upload_offsets.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "state.json")
    t = mod.UploadTracker(p, chunk_size=1024)
    assert t.next_offset("u1") == 0 and t.completed("u1") == []
    t.record_chunk("u1", 0); t.record_chunk("u1", 1)
    assert t.next_offset("u1") == 2048
    t.record_chunk("u1", 3)
    assert t.next_offset("u1") == 2048, "gap at chunk 2 is the resume point"
    t.record_chunk("u1", 2); assert t.next_offset("u1") == 4096
    t.record_chunk("u1", 2); assert t.completed("u1") == [0, 1, 2, 3]
    assert mod.UploadTracker(p, 1024).next_offset("u1") == 4096
    assert t.next_offset("other") == 0
    try:
        t.record_chunk("u1", -1); raise AssertionError("negative must raise")
    except ValueError:
        pass
print("ok")
