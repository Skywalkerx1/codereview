import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("billing/sequence_counter.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "seq.txt")
    c = mod.MonotonicCounter(p)
    assert c.value() == 0
    assert [c.next(), c.next(), c.next()] == [1, 2, 3]
    assert mod.MonotonicCounter(p).value() == 3
    assert mod.MonotonicCounter(p).next() == 4
    seq = [c.next() for _ in range(5)]
    assert seq == sorted(seq) and len(set(seq)) == 5
    pathlib.Path(p).write_text("junk", encoding="utf-8")
    try:
        c.value(); raise AssertionError("corrupt must raise")
    except ValueError:
        pass
print("ok")
