#!/usr/bin/env python3
"""Scripted stub seat for the CodeReview pilot demo.

This is NOT a model. It is a deterministic stand-in that uses
CodeReview's real agent-seat mechanism (see README, "Agent
seats"): CodeReview writes the review prompt to the file named
by $CODEREVIEW_PROMPT (and pipes it to stdin), and the seat
prints exactly one JSON verdict object on stdout.

The stub recognises the demo's one planted defect by the exact
added line that carries it, and answers "pass" for anything
else. It also answers the gate's follow-up passes (re-ground
and cross-family confirmation) in their own JSON shapes, so a
full gate run completes offline with no API keys.
"""

import json
import os
import sys

DEFECT_LINE = ('    return gateway.charge(amount_cents=order.total_dollars, '
               'currency="usd")')
DEFECT_MARKER = "amount_cents=order.total_dollars"


def read_prompt():
    path = os.environ.get("CODEREVIEW_PROMPT")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return sys.stdin.read()


def main():
    prompt = read_prompt()
    defect_present = DEFECT_MARKER in prompt

    if "RE-GROUND pass" in prompt:
        if defect_present:
            print(json.dumps({
                "status": "confirmed",
                "evidence_quote": DEFECT_LINE,
                "reason": "",
            }))
        else:
            print(json.dumps({
                "status": "withdrawn",
                "evidence_quote": "",
                "reason": "defect line not present in the section shown",
            }))
        return

    if "CROSS-FAMILY CONFIRMATION pass" in prompt:
        print(json.dumps({
            "verdict": "confirm" if defect_present else "refute",
            "evidence_quote": DEFECT_LINE if defect_present else "",
            "reason": ("The gateway is passed the dollar amount where "
                       "its API expects integer cents."
                       if defect_present else
                       "The cited defect line is not in the region."),
        }))
        return

    if defect_present:
        print(json.dumps({
            "verdict": "changes_requested",
            "summary": ("charge_order passes the dollar amount to a "
                        "gateway parameter that expects integer cents."),
            "findings": [{
                "severity": "major",
                "category": "correctness",
                "file": "billing.py",
                "line": 27,
                "title": ("Dollar amount passed where the gateway "
                          "expects cents"),
                "evidence": DEFECT_LINE.strip(),
                "evidence_quote": DEFECT_LINE,
                "recommendation": ("Convert before the call: "
                                   "amount_cents = dollars_to_cents("
                                   "order.total_dollars), and pass "
                                   "amount_cents to the gateway."),
                "confidence": 0.95,
            }],
        }))
        return

    print(json.dumps({
        "verdict": "pass",
        "summary": "No issue found in this change under this lens.",
        "findings": [],
    }))


if __name__ == "__main__":
    main()
