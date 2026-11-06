import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("mod", pathlib.Path("app/webhook_verify.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import hashlib, hmac
secret = b"s3cr3t-key"
body = b'{"event":"paid","amount":100}'
sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
assert mod.sign(body, secret) == sig
now = 1_700_000_000
assert mod.verify(body, sig, now, secret, now) is True
assert mod.verify(body, sig, str(now), secret, now) is True  # header string ok
# Tampered body or wrong secret fails
assert mod.verify(body + b" ", sig, now, secret, now) is False
assert mod.verify(body, sig, now, b"wrong", now) is False
# A valid signature for a different body fails
other = hmac.new(secret, b"other", hashlib.sha256).hexdigest()
assert mod.verify(body, other, now, secret, now) is False
# Replay guard: old and far-future timestamps fail even with good sig
assert mod.verify(body, sig, now - 301, secret, now) is False
assert mod.verify(body, sig, now + 301, secret, now) is False
# Exactly at the tolerance boundary passes, both directions
assert mod.verify(body, sig, now - 300, secret, now) is True
assert mod.verify(body, sig, now + 300, secret, now) is True
# Malformed attacker input returns False, never raises
assert mod.verify(body, "not-hex!!", now, secret, now) is False
assert mod.verify(body, sig, "tomorrow", secret, now) is False
assert mod.verify(body, None, now, secret, now) is False
assert mod.verify("text-not-bytes", sig, now, secret, now) is False
# Non-ASCII / binary bodies are signed over raw bytes
raw = bytes(range(256))
assert mod.verify(raw, mod.sign(raw, secret), now, secret, now) is True
print("ok")
