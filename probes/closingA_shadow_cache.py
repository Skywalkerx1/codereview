#!/usr/bin/env python3
"""Closing-A probe — attempt-2 03eb527e1e44 / attempt-1 62576759aaad:
shadow adjudication cache hit overwrites seat/family but allegedly
preserves the FIRST call's 'independence' (and the state derived
from it), so a later reduced-independence caller inherits an
independent-call verdict state.

Run 1: cache a major sustain_refutation under independence=
"independent". Run 2: same finding/region, different seat/family,
independence="reduced", served from the same cache.
Control: a fresh (uncached) reduced-independence run of the same
case — the state the second caller should have produced.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-shadow-cache.txt")

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


def payload(decision="sustain_refutation"):
    return {"claim_restated": "the total lacks a guard",
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


class Seat:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


cache = {}
e1 = core.shadow_adjudicate(
    Seat([payload(), payload()]), dict(FINDING), REGION, dict(DISPUTE),
    seat_name="tl1", seat_family="famC", independence="independent",
    cache=cache)
emit(f"run1 (independent, seat tl1/famC): state={e1['state']!r} "
     f"independence={e1['independence']!r} cache_hit={e1['cache_hit']}")

seat2 = Seat([payload(), payload()])
e2 = core.shadow_adjudicate(
    seat2, dict(FINDING), REGION, dict(DISPUTE),
    seat_name="tl2", seat_family="famD", independence="reduced",
    cache=cache)
emit(f"run2 (reduced, seat tl2/famD, same cache): state={e2['state']!r} "
     f"independence={e2['independence']!r} seat={e2['seat']!r} "
     f"family={e2['family']!r} cache_hit={e2['cache_hit']} "
     f"seat_calls={seat2.calls}")

e3 = core.shadow_adjudicate(
    Seat([payload(), payload()]), dict(FINDING), REGION, dict(DISPUTE),
    seat_name="tl2", seat_family="famD", independence="reduced")
emit(f"control (reduced, NO cache): state={e3['state']!r} "
     f"independence={e3['independence']!r} cache_hit={e3['cache_hit']}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
