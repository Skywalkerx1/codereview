import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/body_reader.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import io

assert mod.read_body(io.BytesIO(b"hello"), max_bytes=16) == b"hello"
assert mod.read_body(io.BytesIO(b""), max_bytes=16) == b""
assert mod.read_body(io.BytesIO(b"x" * 16), max_bytes=16) == b"x" * 16
try:
    mod.read_body(io.BytesIO(b"x" * 5000), max_bytes=1024)
    raise AssertionError("oversized body was accepted")
except ValueError:
    pass
try:
    mod.read_body(io.BytesIO(b"x" * 17), max_bytes=16)
    raise AssertionError("one byte over the cap was accepted")
except ValueError:
    pass
print("ok")
