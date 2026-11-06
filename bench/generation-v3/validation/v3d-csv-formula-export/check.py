import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/notes_export.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import csv, io

out = io.StringIO()
mod.export_notes([
    ["alice", "=2+5+cmd|' /C calc'!A0"],
    ["bob", "+SUM(A1:A9)"],
    ["carol", "an ordinary note"],
    ["dave", "@mention formula"],
], out)
out.seek(0)
rows = list(csv.reader(out))
assert rows[0][1].startswith("'="), rows[0]
assert rows[1][1].startswith("'+"), rows[1]
assert rows[3][1].startswith("'@"), rows[3]
assert rows[2][1] == "an ordinary note"
assert rows[0][0] == "alice"
print("ok")
