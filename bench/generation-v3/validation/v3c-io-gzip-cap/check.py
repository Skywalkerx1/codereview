import gzip, importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("codecs/gzipcap.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# small valid payload decodes fully, cap exactly at size is OK
payload = b"hello world" * 10
blob = gzip.compress(payload)
assert mod.decode_gzip_limited(blob, len(payload)) == payload
assert mod.decode_gzip_limited(blob, len(payload) + 100) == payload
# empty payload with zero cap
assert mod.decode_gzip_limited(gzip.compress(b""), 0) == b""
# one byte under the needed cap raises the cap error, not a silent cut
try:
    mod.decode_gzip_limited(blob, len(payload) - 1); assert False
except mod.SizeCapExceeded:
    pass
# zip bomb: huge ratio stream aborts at a small cap
bomb = gzip.compress(b"\x00" * 5_000_000)
try:
    mod.decode_gzip_limited(bomb, 4096); assert False, "bomb decoded"
except mod.SizeCapExceeded:
    pass
# corrupt data raises the decode error
try:
    mod.decode_gzip_limited(b"this is not gzip at all", 1000); assert False
except mod.GzipDecodeError:
    pass
# truncated stream raises the decode error
try:
    mod.decode_gzip_limited(blob[:len(blob) // 2], 10000); assert False
except mod.GzipDecodeError:
    pass
# trailing garbage after a valid stream is rejected
try:
    mod.decode_gzip_limited(blob + b"junk", 10000); assert False
except mod.GzipDecodeError:
    pass
# negative cap is a plain ValueError
try:
    mod.decode_gzip_limited(blob, -1); assert False
except ValueError:
    pass
# unicode round trip
text = "déjà vu — 中文".encode("utf-8")
assert mod.decode_gzip_limited(gzip.compress(text), 1000) == text
print("ok")
