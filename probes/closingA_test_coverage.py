#!/usr/bin/env python3
"""Closing-A probe — attempt-2 5683aa292958: "New evidence sidecar
attachment code has no test coverage" (recommendation names
_attach_evidence_sidecars and _validate_evidence_sidecars,
covering truncation, hash mismatches, missing sidecar files).

Method (per the assignment): grep tests/ for the function names
and for sidecar behaviour tests; list which test cases exercise
attach / validation (directly or through verify_record), and
whether any test attaches sidecars for a report carrying
shadow_adjudications (the NEW walk added with the shadow section).
Also run the sidecar test classes to confirm they pass at HEAD.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-test-coverage.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


tests_dir = os.path.join(REPO, "tests")
test_files = sorted(f for f in os.listdir(tests_dir)
                    if f.startswith("test_") and f.endswith(".py"))
corpus = {}
for f in test_files:
    with open(os.path.join(tests_dir, f), encoding="utf-8") as fh:
        corpus[f] = fh.read()

for needle in ("_attach_evidence_sidecars",
               "_validate_evidence_sidecars",
               "_iter_evidence_refs",
               "_shadow_evidence_targets",
               "evidence_sidecars",
               "shadow_adjudications"):
    hits = [f"{f}:{len(re.findall(re.escape(needle), txt))}"
            for f, txt in corpus.items() if needle in txt]
    emit(f"grep tests/ {needle!r}: {hits or 'NO HITS'}")

emit("")
emit("sidecar test cases found:")
for f, txt in corpus.items():
    for m in re.finditer(r"def (test_\w*(?:sidecar|quote_round)\w*)\(",
                         txt):
        emit(f"  {f}: {m.group(1)}")
emit("")
shadow_sidecar = [f for f, txt in corpus.items()
                  if "shadow_adjudications" in txt
                  and "sidecar" in txt.lower()]
emit(f"files mentioning BOTH shadow_adjudications and sidecar: "
     f"{shadow_sidecar or 'NONE'}")

proc = subprocess.run(
    [sys.executable, "-m", "unittest",
     "tests.test_v100_integration.EvidenceSidecarTests",
     "tests.test_v111_hardening.NonDictEntryTests", "-v"],
    cwd=REPO, capture_output=True, text=True, timeout=300,
    env={**os.environ, "PYTHONPATH": os.path.join(REPO, "src")})
tail = (proc.stderr or proc.stdout).strip().splitlines()
emit(f"unittest sidecar classes exit={proc.returncode}: "
     f"{tail[-1] if tail else ''} "
     f"({sum(1 for ln in tail if ln.rstrip().endswith('ok'))} tests ok)")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
