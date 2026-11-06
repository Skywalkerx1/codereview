import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("mailbuild/headers.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# ordinary headers pass through unchanged
h = mod.build_message_headers("user@example.com", "Your receipt")
assert h == {"To": "user@example.com", "Subject": "Your receipt"}
# unicode names and subjects are NOT rejected
h = mod.build_message_headers("josé@example.com", "Réunion — 会议提醒 🎉")
assert h["Subject"] == "Réunion — 会议提醒 🎉"
assert mod.format_sender("Jürgen Böb", "j@example.com") == \
    "Jürgen Böb <j@example.com>"
# CRLF smuggling an extra header is refused in either field
for bad in ("victim@example.com\r\nBcc: spy@evil.test",
            "victim@example.com\nBcc: spy@evil.test"):
    try:
        mod.build_message_headers(bad, "hi"); assert False, bad
    except mod.HeaderInjectionError:
        pass
for bad_subject in ("Hi\r\nX-Injected: 1", "Hi\nthere", "Hi\rthere"):
    try:
        mod.build_message_headers("user@example.com", bad_subject)
        assert False, bad_subject
    except mod.HeaderInjectionError:
        pass
# a lone CR or LF anywhere counts, even at the edges
try:
    mod.build_message_headers("user@example.com", "trailing\n")
    assert False
except mod.HeaderInjectionError:
    pass
# sender formatting applies the same rule to the display name
try:
    mod.format_sender("Evil\r\nBcc: spy@evil.test", "e@example.com")
    assert False
except mod.HeaderInjectionError:
    pass
# malformed recipients and empty subject are plain ValueErrors
for bad_addr in ("", "no-at-sign", "@example.com", "user@",
                 "a@b@c"):
    try:
        mod.build_message_headers(bad_addr, "hi"); assert False, bad_addr
    except ValueError:
        pass
try:
    mod.build_message_headers("user@example.com", "   "); assert False
except ValueError:
    pass
# bare sender address renders without brackets-name when name is empty
assert mod.format_sender("", "solo@example.com") == "solo@example.com"
print("ok")
