#!/usr/bin/env python3
"""Closing-A probe — attempt-2 531bd4e5a458: evidence-sidecar
verification allegedly accepts refs with empty or malformed
sha256 values.

Drive core._validate_evidence_sidecars directly with hand-made
refs: empty sha, non-hex sha, well-formed-but-absent sha, and a
path-traversal sha naming a REAL file outside the evidence dir.
Control: a genuine ref produced by _attach_evidence_sidecars.
"Accepted" would mean the problems list comes back empty.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-sidecar-sha.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def record_with_ref(sha):
    return {"findings": [{
        "id": "f1", "evidence": "hello world text",
        "evidence_ref": {"sha256": sha, "length": 16,
                         "truncated": False}}]}


with tempfile.TemporaryDirectory() as td:
    ev = os.path.join(td, "evidence")
    os.makedirs(ev)
    # A real file OUTSIDE the evidence dir, for the traversal case.
    outside = os.path.join(td, "outside.txt")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write("hello world text")
    for label, sha in (("empty", ""),
                       ("non-hex", "zz-not-a-hash"),
                       ("well-formed absent", "a" * 64),
                       ("traversal to real file", "../outside.txt")):
        problems = core._validate_evidence_sidecars(
            record_with_ref(sha), ev)
        emit(f"sha={label} ({sha!r}): problems={problems}")

    # Control: genuine attach -> validate must be clean.
    report = {"findings": [{"id": "f2", "evidence": "hello world text"}]}
    written = core._attach_evidence_sidecars(report, td)
    problems = core._validate_evidence_sidecars(written, ev)
    emit(f"control (genuine ref): problems={problems}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
