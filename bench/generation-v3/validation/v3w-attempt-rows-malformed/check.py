import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/attempt_rows.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def write(text):
    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8")
    fh.write(text); fh.close()
    return fh.name


# Clean file: all rows parsed, nothing malformed.
rows, malformed = mod.parse_attempt_rows(
    write('{"a": 1}\n\n{"b": 2}\n'))
assert (len(rows), malformed) == (2, 0), (rows, malformed)

# Empty file.
rows, malformed = mod.parse_attempt_rows(write(""))
assert (rows, malformed) == ([], 0), (rows, malformed)

# The incident shape: valid, blank, MALFORMED, valid. The scan
# must complete with the good rows and the malformed count.
path = write('{"seats": [{"provider": "a"}]}\n'
             "\n"
             '{"seats": [BROKEN\n'
             '{"seats": [{"provider": "b"}]}\n')
rows, malformed = mod.parse_attempt_rows(path)
assert len(rows) == 2 and malformed == 1, (rows, malformed)
assert [r["seats"][0]["provider"] for r in rows] == ["a", "b"]

# Non-object JSON lines count as malformed too.
rows, malformed = mod.parse_attempt_rows(
    write('42\n["x"]\n"str"\n{"ok": true}\n'))
assert rows == [{"ok": True}] and malformed == 3, (rows, malformed)
print("ok")
