import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("downloads/names.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
s = mod.sanitize_download_name

# ordinary names pass through untouched
assert s("quarterly report.pdf") == "quarterly report.pdf"
assert s("résumé-2026.docx") == "résumé-2026.docx"
# directory components stripped for both separator styles
assert s("/var/tmp/../../etc/passwd") == "passwd"
assert s("C:\\Users\\x\\Downloads\\photo.jpg") == "photo.jpg"
assert s("a/b\\c/file.txt") == "file.txt"
# control characters removed
assert s("re\x00port\x1f.pdf") == "report.pdf"
assert s("ta\tb.txt") == "tab.txt"
# trailing dots and spaces removed
assert s("notes.txt...") == "notes.txt"
assert s("draft.doc   ") == "draft.doc"
assert s("name... .txt") == "name... .txt"
assert s("file.txt.") == "file.txt"
# reserved device names neutralised, case-insensitively, with/without ext
assert s("CON.txt") == "_CON.txt"
assert s("con") == "_con"
assert s("nul.pdf") == "_nul.pdf"
assert s("COM1") == "_COM1"
assert s("lpt9.txt") == "_lpt9.txt"
# merely similar names are not reserved
assert s("console.txt") == "console.txt"
assert s("COM10.txt") == "COM10.txt"
# length cap keeps the extension
long_name = "a" * 100 + ".pdf"
out = s(long_name, max_length=40)
assert len(out) == 40 and out.endswith(".pdf") and out.startswith("a")
out = s("b" * 100, max_length=20)
assert len(out) == 20
# unusable inputs fall back
assert s("") == "download"
assert s("...") == "download"
assert s("///") == "download"
assert s(None) == "download"
# too-small cap is an error
try:
    s("x.txt", max_length=4); assert False
except ValueError:
    pass
print("ok")
