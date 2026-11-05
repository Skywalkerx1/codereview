#!/usr/bin/env python3
"""Closing-A probe — attempt-1 f43f2968433d: verify_chain allegedly
crashes with UnboundLocalError on chain_consumed when called with
the documented default dispositions=None (the refutation concedes
the mechanism in the cited code; verify the state at HEAD).

Call verify_chain with a minimal two-record chain, once with no
dispositions argument at all and once with an explicit store.
"""

import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-verify-chain.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


R1 = {"mode": "review", "gate": "blocked",
      "coverage": {"complete": True}, "findings": [],
      "reviewer_reports": [], "patch_sha256": "0" * 64,
      "head": None}
R2 = {"mode": "verify", "gate": "pass",
      "test_results": [{"command": "t", "ok": True}],
      "cleared": [], "reviewer_reports": [], "head": None}
src, start = inspect.getsourcelines(core.verify_chain)
for i, ln in enumerate(src):
    if "chain_consumed" in ln:
        emit(f"core.py:{start + i}: {ln.rstrip()}")
try:
    res = core.verify_chain([dict(R1), dict(R2)])
    emit(f"verify_chain(no dispositions arg) RETURNED: "
         f"eligible={res['eligible']} checks={len(res['checks'])} "
         f"'dispositions_consumed' in result: "
         f"{'dispositions_consumed' in res}")
except BaseException as exc:  # noqa: BLE001
    emit(f"verify_chain(no dispositions arg) RAISED "
         f"{type(exc).__name__}: {exc}")
try:
    res2 = core.verify_chain([dict(R1), dict(R2)], dispositions=[])
    emit(f"verify_chain(dispositions=[]) RETURNED: "
         f"dispositions_consumed={res2.get('dispositions_consumed')}")
except BaseException as exc:  # noqa: BLE001
    emit(f"verify_chain(dispositions=[]) RAISED "
         f"{type(exc).__name__}: {exc}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
