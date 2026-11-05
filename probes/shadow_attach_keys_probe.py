#!/usr/bin/env python3
"""Attach-keys null-lookup probe — shadow-branch review, for
97feb799979e (refutation-weak): "attach_function_keys calls
source_lookup(path) without null check."

Claim: `attach_function_keys` stores `source_lookup(path)`
in a cache and passes it to `function_key` — if the lookup
returns None (or raises), the claim holds, a missing null
check lets None flow into function_key. The refutation
answers that the call is wrapped in try/except storing None
on exception — which describes how None ARRIVES, not what
happens next; neither side cites the callee.

Probe: (1) function_key's own first line at HEAD —
`if not source or not line: return None` — the None check
lives in the callee; call function_key(None, n) and
function_key("", n) directly. (2) attach_function_keys with
three lookups: returns-None, raises, and returns-real-source
for one path + None for an absent path (the production
shape: run_review passes the precedent store's
source_lookup, core.py — its None IS the normal "path not
in the snapshot" miss). Record keyed counts and exceptions
for each. (3) Confirm the per-path cache: a raising lookup
is called once per path, not once per finding.

Exit 0 = no exception anywhere and the keyed counts match
the design (None source -> no key, finding stays on the
legacy line-based path)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS,
                   "shadow-attach-keys-97feb799979e.txt")

SOURCE = ("def compute_total(items):\n"
          "    return sum(items)\n"
          "\n"
          "VALUE = compute_total(items)\n")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def findings():
    return [{"id": "k1", "file": "mod.py", "line": 2},
            {"id": "k2", "file": "mod.py", "line": 4},
            {"id": "k3", "file": "gone.py", "line": 1}]


emit("callee guard — function_key(source, line) first "
     "executable check at HEAD:")
import inspect
fk_src = inspect.getsource(core.function_key)
guard = [ln.strip() for ln in fk_src.splitlines()
         if "if not source" in ln]
emit(f"  {guard}")
emit(f"  function_key(None, 2) -> {core.function_key(None, 2)}")
emit(f"  function_key('', 2)   -> {core.function_key('', 2)}")
assert core.function_key(None, 2) is None
assert core.function_key("", 2) is None

emit("")
emit("attach_function_keys under three lookups:")
for label, lookup in (
        ("returns None for every path",
         lambda _p: None),
        ("raises for every path",
         lambda _p: 1 / 0),
        ("real source for mod.py, None for gone.py",
         lambda p: SOURCE if p == "mod.py" else None)):
    fs = findings()
    keyed = core.attach_function_keys(fs, lookup)
    got = [f["id"] for f in fs if "function_key" in f]
    emit(f"  {label}: keyed={keyed}, keyed ids={got}, "
         f"no exception")
    if label.startswith("real source"):
        assert keyed == 1 and got == ["k1"], (keyed, got)
    else:
        assert keyed == 0 and got == [], (keyed, got)

emit("")
calls = []
def counting_lookup(_p):
    calls.append(_p)
    raise RuntimeError("snapshot miss")
core.attach_function_keys(findings(), counting_lookup)
emit(f"raising lookup invoked once per distinct path: "
     f"{len(calls)} call(s) for 2 distinct paths "
     f"(cache stores the None)")
assert len(calls) == 2

emit("")
emit("VERDICT FACTS: a None or raising source_lookup never "
     "crashes attach_function_keys and never keys a finding "
     "— the None handling the claim asks for exists, one "
     "level down, as function_key's opening guard. The "
     "refutation's cited try/except is real but is not the "
     "mechanism that makes this safe; the claim's demanded "
     "call-site check would be redundant.")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
