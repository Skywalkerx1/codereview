import importlib.util, io, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("ingest/bounded_reader.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# exact fit and empty body pass
assert mod.read_bytes_limited(b"hello", 5) == "hello"
assert mod.read_bytes_limited(b"", 0) == ""
assert mod.read_bytes_limited(b"", 10) == ""
# valid multibyte UTF-8 within the byte (not char) limit passes
assert mod.read_bytes_limited("héllo".encode("utf-8"), 6) == "héllo"
# one byte over the limit raises the specific error, never truncates
try:
    mod.read_bytes_limited(b"hello!", 5); assert False, "oversize accepted"
except mod.BoundedReadError:
    pass
# oversize detected on a stream, large body
try:
    mod.read_bounded(io.BytesIO(b"x" * 100000), 100); assert False
except mod.BoundedReadError:
    pass
# zero limit rejects a single byte
try:
    mod.read_bytes_limited(b"a", 0); assert False
except mod.BoundedReadError:
    pass
# invalid UTF-8 raises the contract error, not UnicodeDecodeError-as-is
# and never a replacement-character string
try:
    mod.read_bytes_limited(b"\xff\xfe bad", 100); assert False
except mod.BoundedReadError:
    pass
# truncated multibyte sequence raises too
try:
    mod.read_bytes_limited("héllo".encode("utf-8")[:2], 100); assert False
except mod.BoundedReadError:
    pass
# negative limit is a plain ValueError before reading
try:
    mod.read_bytes_limited(b"hi", -1); assert False
except ValueError:
    pass
# a stream that yields small chunks is reassembled correctly
class Dribble:
    def __init__(self, data): self._buf = io.BytesIO(data)
    def read(self, n): return self._buf.read(min(n, 2))
assert mod.read_bounded(Dribble(b"abcdef"), 6) == "abcdef"
try:
    mod.read_bounded(Dribble(b"abcdef"), 5); assert False
except mod.BoundedReadError:
    pass
print("ok")
