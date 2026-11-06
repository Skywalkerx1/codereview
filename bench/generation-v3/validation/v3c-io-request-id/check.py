import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("tracing/requestid.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

fixed = lambda: "fixedgen-id-0001"

# valid incoming IDs propagate unchanged (charset + length)
assert mod.resolve_request_id("abc12345") == "abc12345"
assert mod.resolve_request_id("Req-2026.11_05-xyz") == "Req-2026.11_05-xyz"
assert mod.resolve_request_id("a" * 64) == "a" * 64
assert mod.resolve_request_id("a" * 8) == "a" * 8
# too short / too long are replaced via the generator
assert mod.resolve_request_id("short", generator=fixed) == "fixedgen-id-0001"
assert mod.resolve_request_id("a" * 65, generator=fixed) == "fixedgen-id-0001"
# unsafe characters are replaced: space, slash, CRLF, unicode, quote
for bad in ("has space12", "slash/id-123", "line\nbreak1",
            "cr\rinject12", "ünïcode-id", 'quote"id-123', ""):
    assert mod.resolve_request_id(bad, generator=fixed) == \
        "fixedgen-id-0001", bad
# missing ID is replaced
assert mod.resolve_request_id(None, generator=fixed) == "fixedgen-id-0001"
# default generation produces a valid, fresh ID each time
one = mod.resolve_request_id(None)
two = mod.resolve_request_id("!!bad!!")
assert mod.is_valid_request_id(one) and mod.is_valid_request_id(two)
assert one != two and len(one) == 32
# a generator returning junk does not leak through: fallback is valid
out = mod.resolve_request_id(None, generator=lambda: "bad id!")
assert mod.is_valid_request_id(out) and out != "bad id!"
# validator boundary checks agree with the resolver
assert mod.is_valid_request_id("x" * 7) is False
assert mod.is_valid_request_id("x" * 8) is True
assert mod.is_valid_request_id(12345678) is False
print("ok")
