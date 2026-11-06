import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("ingest/jsonl_reader.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

recs = mod.read_jsonl('{"a": 1}\n{"b": 2}\n')
assert recs == [{"a": 1}, {"b": 2}]
# blank lines skipped, including whitespace-only and trailing
recs = mod.read_jsonl('{"a": 1}\n\n   \n{"b": 2}\n\n')
assert recs == [{"a": 1}, {"b": 2}]
assert mod.read_jsonl("") == []
assert mod.read_jsonl("\n\n") == []
# malformed line names its line number; nothing is returned
try:
    mod.read_jsonl('{"a": 1}\n{"b": 2}\nnot json\n{"c": 3}\n'); assert False
except ValueError as exc:
    assert "line 3" in str(exc), exc
# non-object JSON is an error naming the line, not a silent record
try:
    mod.read_jsonl('{"a": 1}\n[1, 2, 3]\n'); assert False
except ValueError as exc:
    assert "line 2" in str(exc), exc
# unicode values survive intact
recs = mod.read_jsonl('{"name": "caf\u00e9"}\n')
assert recs[0]["name"] == "café"
# nested objects and numbers keep their types
recs = mod.read_jsonl('{"x": {"y": [1, 2.5, null]}}\n')
assert recs[0]["x"]["y"][1] == 2.5 and recs[0]["x"]["y"][2] is None
print("ok")
