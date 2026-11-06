import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("uploads/typeguard.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
v = mod.validate_upload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 32

# agreement passes and returns the canonical name
assert v("image/png", PNG) == "png"
assert v("image/jpeg", JPEG) == "jpeg"
assert v("application/pdf", PDF) == "pdf"
# declared type: case-insensitive, parameters ignored, jpg alias
assert v("IMAGE/PNG", PNG) == "png"
assert v("image/jpeg; charset=binary", JPEG) == "jpeg"
assert v("image/jpg", JPEG) == "jpeg"
# mismatches rejected in every direction
for declared, data in (("image/png", JPEG), ("image/png", PDF),
                       ("application/pdf", PNG), ("image/jpeg", PDF)):
    try:
        v(declared, data); assert False, declared
    except mod.UploadTypeError:
        pass
# unknown declared types rejected even with valid content
for declared in ("image/gif", "text/plain", "", "image/png2"):
    try:
        v(declared, PNG); assert False, declared
    except mod.UploadTypeError:
        pass
# content matching no supported signature rejected
try:
    v("image/png", b"GIF89a" + b"\x00" * 16); assert False
except mod.UploadTypeError:
    pass
# truncated magic and empty data rejected
try:
    v("image/png", b"\x89PNG"); assert False
except mod.UploadTypeError:
    pass
try:
    v("application/pdf", b""); assert False
except mod.UploadTypeError:
    pass
# minimal exact-length signatures are enough
assert v("image/jpeg", b"\xff\xd8\xff") == "jpeg"
assert v("application/pdf", b"%PDF-") == "pdf"
# sniff helper agrees with the validator
assert mod.sniff_type(PNG) == "png"
assert mod.sniff_type(b"plain text") is None
print("ok")
