import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("app/hmac_keys.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Ordinary secrets pass through.
assert mod.prepare_hmac_key("s3cr3t-signing-key") == \
    b"s3cr3t-signing-key"
assert mod.prepare_hmac_key(b"raw-bytes") == b"raw-bytes"
assert mod.is_usable_secret("ordinary")

# Asymmetric PUBLIC key material must be refused: it is not
# secret, so anyone holding it could forge HMAC tokens.
for pub in (
    "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZI"
    "zj0DAQcDQgAE\n-----END PUBLIC KEY-----",
    "-----BEGIN RSA PUBLIC KEY-----\nMIIBCgKCAQEA\n"
    "-----END RSA PUBLIC KEY-----",
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 example@host",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample host",
):
    try:
        prepared = mod.prepare_hmac_key(pub)
        raise AssertionError(f"public key accepted: {prepared!r}")
    except TypeError:
        pass
    assert not mod.is_usable_secret(pub)
print("ok")
