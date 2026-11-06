"""Behavioural check for v3r-json-tool-utf8.

Pre-fix behaviour: the formatter opened its input and output
without an explicit encoding, so the files were decoded and
encoded with the locale encoding.  On a machine whose locale was
not UTF-8 (for example an ASCII C locale), formatting a valid
UTF-8 JSON document containing non-ASCII text failed with
UnicodeDecodeError, and non-ASCII output could fail the same way.

This check simulates such a locale by shimming builtins.open so
that any text-mode open that does NOT name an encoding falls back
to ASCII.  Code that pins encoding="utf-8" on both files (the
fix) is unaffected by the shim.
"""

import builtins
import importlib.util
import json
import pathlib
import tempfile

spec = importlib.util.spec_from_file_location(
    "jsonfmt", pathlib.Path("app/jsonfmt.py"))
jsonfmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jsonfmt)

real_open = builtins.open


def ascii_default_open(file, mode="r", buffering=-1, encoding=None,
                       errors=None, newline=None, closefd=True,
                       opener=None):
    if "b" not in mode and encoding is None:
        encoding = "ascii"
    return real_open(file, mode, buffering, encoding, errors,
                     newline, closefd, opener)


def run_main(argv):
    builtins.open = ascii_default_open
    try:
        return jsonfmt.main(argv)
    finally:
        builtins.open = real_open


payload = '{"msg": "こんにちは", "n": 1}'
expected_obj = {"msg": "こんにちは", "n": 1}

with tempfile.TemporaryDirectory() as tmp:
    src = pathlib.Path(tmp) / "in.json"
    dst = pathlib.Path(tmp) / "out.json"
    with real_open(src, "w", encoding="utf-8") as fh:
        fh.write(payload)

    # The fix lets the tool run under a non-UTF-8 locale default.
    assert run_main([str(src), str(dst)]) == 0
    text = dst.read_text(encoding="utf-8")
    # The document round-trips through the formatter.
    assert json.loads(text) == expected_obj
    # Output is exactly the indented, ASCII-escaped serialisation.
    assert text == json.dumps(expected_obj, indent=4) + "\n"
    assert "\\u3053" in text

    # Sorted-keys mode works under the same simulated locale.
    src2 = pathlib.Path(tmp) / "in2.json"
    dst2 = pathlib.Path(tmp) / "out2.json"
    with real_open(src2, "w", encoding="utf-8") as fh:
        fh.write('{"b": 1, "a": "é"}')
    assert run_main(["--sort-keys", str(src2), str(dst2)]) == 0
    assert dst2.read_text(encoding="utf-8") == \
        json.dumps({"a": "é", "b": 1}, indent=4, sort_keys=True) + "\n"

print("v3r-json-tool-utf8: OK")
