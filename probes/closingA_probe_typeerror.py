#!/usr/bin/env python3
"""Closing-A probe — fixes-review 21bb4af17e22: the 849e70e wiring
fix in shadow_adjudicate catches ALL TypeError around the
probe_fn(finding, request) call, so a probe_fn with the CORRECT
two-arg signature whose BODY raises TypeError allegedly gets
misclassified as status "wiring_error".

Drive the production shadow path (shadow_adjudicate with a
needs_probe draw) with:
 A) a correct-signature probe_fn whose body raises TypeError
    from an internal operation;
 B) a correct-signature probe_fn whose body raises RuntimeError
    (contrast: the generic probe-failure path);
 C) the REAL harness probe_fn (probe.make_probe_fn) executing a
    spec whose probe CODE raises TypeError inside the sandbox —
    does that surface as wiring_error or as a probe outcome?
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core, probe  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-probe-typeerror.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


REGION = ("import os\n"
          "VALUE = compute_total(items)\n"
          "print(VALUE)\n"
          "RESULT = VALUE * 2\n")
FINDING = {"id": "fx1", "file": "app.py", "line": 2,
           "severity": "major", "title": "Total without guard",
           "evidence": "VALUE = compute_total(items)",
           "evidence_quote": "VALUE = compute_total(items)"}
DISPUTE = {"by": "seatB", "family": "famB", "raiser_family": "famA",
           "evidence_quote": "print(VALUE)",
           "reason": "the claim fails on the printed value"}
SPEC = {"kind": "python", "code": "print('MARKER')"}


def payload(decision="sustain_refutation", **over):
    p = {"claim_restated": "the total lacks a guard",
         "claim_falsifiable": True,
         "position_a_addresses_claim": {"value": True,
                                        "why": "a addresses"},
         "position_b_addresses_claim": {"value": False,
                                        "why": "b misses"},
         "reasoning_assessment": {
             "claim_valid": False, "refutation_validity": "valid"},
         "deciding_evidence": {"quote": "print(VALUE)"},
         "probe_request": None,
         "decision": decision,
         "severity_after_rubric": {"level": "major",
                                   "rubric_clause": None},
         "confidence": "high",
         "rationale": "the code shows it"}
    p.update(over)
    return p


class Seat:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def __call__(self, prompt):
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


def seat_with_probe():
    return Seat([payload(decision="needs_probe", probe_request=SPEC),
                 payload(), payload()])


def run(label, probe_fn):
    entry = core.shadow_adjudicate(
        seat_with_probe(), dict(FINDING), REGION, dict(DISPUTE),
        seat_name="tl", seat_family="famC", probe_fn=probe_fn)
    emit(f"{label}: probe_result={entry['probe_result']}")


def internal_typeerror(finding, request):
    # Correct two-arg signature; the TypeError comes from INSIDE
    # the body (an ordinary implementation bug), not from binding.
    return {"outcome": 1 + "one"}  # noqa: unsupported operand


def internal_runtime(finding, request):
    raise RuntimeError("probe implementation exploded")


run("A internal TypeError, correct signature", internal_typeerror)
run("B internal RuntimeError, correct signature", internal_runtime)

tree = tempfile.mkdtemp(prefix="codereview-typeerror-tree-")
try:
    real_fn = probe.make_probe_fn(tree, timeout=30)
    bad_spec = {"kind": "python",
                "code": "raise TypeError('spec-internal type error')"}
    entry = core.shadow_adjudicate(
        Seat([payload(decision="needs_probe", probe_request=bad_spec),
              payload(), payload()]),
        dict(FINDING), REGION, dict(DISPUTE),
        seat_name="tl", seat_family="famC", probe_fn=real_fn)
    emit(f"C real make_probe_fn, spec code raises TypeError: "
         f"probe_result status={entry['probe_result'].get('status')!r} "
         f"outcome={entry['probe_result'].get('outcome')!r}")
finally:
    shutil.rmtree(tree, ignore_errors=True)

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
