import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/capture.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Whole capture: bytes unchanged, no markers.
out = mod.combine_output(b"ready\n", b"")
assert out == b"ready\n", out

# Capped capture: truncation marker present.
out = mod.combine_output(b"data", b"", truncated=True)
assert b"output truncated" in out, out

# Partial capture (detached pipe holder): the record must SAY
# the capture is incomplete -- never present partial as whole.
out = mod.combine_output(b"ready\n", b"", incomplete=True)
assert b"capture incomplete" in out, out
print("ok")
