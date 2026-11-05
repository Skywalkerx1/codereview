#!/usr/bin/env python3
"""Closing-A probe — attempt-2 b2b1f776d566 (archived rule excludes
any top-level review-* directory) and attempt-1 0011f9970c38
(archived rule too narrow: nested review dirs not matched).
Both concern core._archived_rule; one matrix settles both.
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
OUT = os.path.join(RESULTS, "closingA-archived-rule.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


emit("docstring of _archived_rule:")
for ln in (core._archived_rule.__doc__ or "").splitlines():
    emit(f"  {ln}")
emit("")
CASES = [
    "review-closing-r1/codereview-1.json",   # top-level review- dir
    "review_v15/out.json",                   # top-level review_ dir
    "review-tools/real_source.py",           # top-level review-* with code
    "docs/review-v15/out.json",              # nested (attempt-1 case)
    "src/deep/review-r1/out.json",           # mid-path review dir
    "review-r1",                             # single component (a file?)
    "src/app.py",                            # ordinary source
    "gate-attempts.log",                     # ledger at top
    "docs/gate-attempts.2026.log",           # ledger nested
]
for path in CASES:
    emit(f"_archived_rule({path!r}) -> {core._archived_rule(path)!r}")
emit(f"function location: core.py line "
     f"{inspect.getsourcelines(core._archived_rule)[1]}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
