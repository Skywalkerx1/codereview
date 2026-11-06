import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/payload_decoder.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Valid UTF-8 round-trips exactly, including non-ASCII text.
assert mod.decode_payload("name=José&city=北京".encode("utf-8")) == "name=José&city=北京"
assert mod.decode_payload(b"plain ascii") == "plain ascii"
assert mod.decode_payload(b"") == ""
# Latin-1 bytes that are not valid UTF-8 must raise, not decode.
for bad in (b"name=caf\xe9", b"\xff\xfe invalid", b"price=\xa310"):
    try:
        mod.decode_payload(bad)
        raise AssertionError(f"invalid UTF-8 accepted: {bad!r}")
    except ValueError:
        pass
fields = mod.decode_fields("a=1&b=2&c=3".encode("utf-8"), {"a", "c"})
assert fields == {"a": "1", "c": "3"}, fields
print("ok")
