import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mod", pathlib.Path("gateway/clientip.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
r = mod.resolve_client_ip
TRUSTED = {"10.0.0.1", "10.0.0.2"}

# untrusted peer: header ignored completely, peer returned --
# even a plausible-looking XFF cannot spoof the client IP
assert r("203.0.113.9", "1.2.3.4", TRUSTED) == "203.0.113.9"
assert r("203.0.113.9", None, TRUSTED) == "203.0.113.9"
# trusted peer, no/empty header: peer returned
assert r("10.0.0.1", None, TRUSTED) == "10.0.0.1"
assert r("10.0.0.1", "", TRUSTED) == "10.0.0.1"
assert r("10.0.0.1", "  , ", TRUSTED) == "10.0.0.1"
# trusted peer, single real client behind it
assert r("10.0.0.1", "198.51.100.7", TRUSTED) == "198.51.100.7"
# chain: client -> trusted proxy -> our trusted peer; the
# first untrusted address FROM THE RIGHT wins
assert r("10.0.0.1", "198.51.100.7, 10.0.0.2", TRUSTED) == "198.51.100.7"
# a forged leftmost entry is NOT taken: an untrusted middle hop
# terminates the walk, since it could have written anything left of it
assert r("10.0.0.1", "6.6.6.6, 198.51.100.7, 10.0.0.2", TRUSTED) == \
    "198.51.100.7"
# entries are trimmed; trusted set given as a list also works
assert r("10.0.0.1", "  198.51.100.7 ,  10.0.0.2 ", ["10.0.0.1", "10.0.0.2"]) \
    == "198.51.100.7"
# entire chain trusted: leftmost entry is the client
assert r("10.0.0.1", "10.0.0.2", TRUSTED) == "10.0.0.2"
# peer trusted but XFF names the peer itself repeatedly
assert r("10.0.0.1", "192.0.2.55, 10.0.0.1", {"10.0.0.1"}) == "192.0.2.55"
print("ok")
