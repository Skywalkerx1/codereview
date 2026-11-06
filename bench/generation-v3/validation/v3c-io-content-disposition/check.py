import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("httputil/disposition.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
e = mod.extract_filename

# plain quoted and unquoted filenames
assert e('attachment; filename="report.pdf"') == "report.pdf"
assert e("attachment; filename=data.csv") == "data.csv"
# RFC 5987 filename* is preferred and UTF-8 decoded
assert e("attachment; filename=\"fallback.txt\"; "
         "filename*=UTF-8''%E2%82%ACrates.txt") == "€rates.txt"
assert e("attachment; filename*=UTF-8''caf%C3%A9.pdf") == "café.pdf"
# filename* with a language tag still decodes
assert e("attachment; filename*=UTF-8'en'%E2%82%AC.txt") == "€.txt"
# malformed filename* falls back to filename=
assert e('attachment; filename="ok.txt"; filename*=not-a-triple') == "ok.txt"
# quoted filename may contain a semicolon
assert e('attachment; filename="a;b.txt"') == "a;b.txt"
# traversal in either parameter is stripped to the bare name
assert e('attachment; filename="../../etc/passwd"') == "passwd"
assert e(r'attachment; filename="..\..\secret.doc"') == "secret.doc"
assert e("attachment; filename*=UTF-8''..%2F..%2Fevil.sh") == "evil.sh"
# missing / empty headers and unusable names give None
assert e(None) is None
assert e("") is None
assert e("attachment") is None
assert e('attachment; filename=""') is None
assert e('attachment; filename="../"') is None
# case-insensitive parameter names
assert e('ATTACHMENT; FILENAME="Upper.PDF"') == "Upper.PDF"
print("ok")
