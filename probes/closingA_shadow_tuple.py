#!/usr/bin/env python3
"""Closing-A probe — attempt-2 ba2479886886: write_report allegedly
crashes when shadow_adjudications are present due to a tuple
unpack mismatch against _shadow_evidence_targets (which yields
3-tuples) in _iter_evidence_refs / _attach_evidence_sidecars.

Build a report carrying a fully populated shadow adjudication
entry (every field _shadow_evidence_targets walks), then run the
real write path: write_report -> _attach_evidence_sidecars, and
_validate_evidence_sidecars over the result.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-shadow-tuple.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


ENTRY = {
    "finding_id": "fx1", "mode": "shadow", "binding": False,
    "claim_restated": "the claim " + "x" * 700,
    "deciding_evidence": {"file": "a.py", "line": 1,
                          "quote": "deciding quote " + "y" * 450},
    "raiser_evidence_addresses_claim": {"value": True,
                                        "why": "raiser why " + "z" * 650},
    "refuter_evidence_addresses_claim": {"value": False,
                                         "why": "refuter why"},
    "draws": [{"deciding_quote": "dq " + "q" * 450,
               "rationale": "draw rationale " + "r" * 650}],
    "probe_result": {"status": "pass",
                     "detail": "probe detail " + "d" * 2100,
                     "evidence_quote": "probe quote " + "p" * 450},
}
triples = list(core._shadow_evidence_targets(ENTRY))
emit(f"_shadow_evidence_targets yields {len(triples)} tuples, "
     f"arities={sorted({len(t) for t in triples})}")

REPORT = {"mode": "review", "gate": "blocked", "created_at": "t",
          "patch_sha256": "0" * 64, "findings": [],
          "shadow_adjudications": [ENTRY]}
try:
    with tempfile.TemporaryDirectory() as td:
        jpath, mpath = core.write_report(REPORT, td, stem="probe")
        written = json.load(open(jpath, encoding="utf-8"))
        entry = written["shadow_adjudications"][0]
        refs = [k for k in entry if k.endswith("_ref")]
        emit(f"write_report SUCCEEDED: {os.path.basename(jpath)}, "
             f"{os.path.basename(mpath)}")
        emit(f"shadow entry top-level refs: {refs}; "
             f"sidecars block: {written.get('evidence_sidecars')}")
        problems = core._validate_evidence_sidecars(
            written, os.path.join(td, "evidence"))
        emit(f"_validate_evidence_sidecars problems: {problems}")
        iter_refs = list(core._iter_evidence_refs(written))
        emit(f"_iter_evidence_refs over written record: "
             f"{len(iter_refs)} refs")
except BaseException as exc:  # noqa: BLE001
    emit(f"write_report RAISED {type(exc).__name__}: {exc}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
