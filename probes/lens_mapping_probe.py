#!/usr/bin/env python3
"""Lens-mapping permutation probe — open-refutations
solution §3, for 35dbb7d20941 (bucket A #2): "Verification
can use a fallback configured for a different lens than the
one originally assigned."

The claim's premise imagines 'more than two lenses in play'.
At HEAD there are exactly two lenses (core.LENSES =
correctness, operations). The probe derives the expected
lens assignment from the same function the review path uses
(core._reviewer_tasks) and, over every provider ordering and
every choice of failing seat, asserts that the fallback which
serves a failed verification seat is the fallback configured
for the lens that seat was assigned — never the other lens's.

Cases: 2 seats in both orderings x each seat failing; a
single seat (serves both lenses); 3 seats (cycling). A
'quota' error keeps every fake to one attempt; verification
payload is an empty-resolutions JSON.

Exit 0 = agreement in every case."""

import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

EMPTY_VERIFY = json.dumps({"resolutions": [], "new_findings": []})
PREV = {"findings": [], "gate": "blocked", "mode": "review"}


def fail(prompt):
    raise RuntimeError("quota exhausted")


def ok(prompt):
    return EMPTY_VERIFY


def expected_lenses(provider_items):
    """seat -> [lenses] exactly as the review path assigns."""
    out = {}
    for name, _seat, lens in core._reviewer_tasks(provider_items):
        out.setdefault(name, []).append(lens)
    return out


def run_case(seat_names, failing):
    providers = {n: (fail if n == failing else ok)
                 for n in seat_names}
    items = [(n, providers[n]) for n in seat_names]
    lenses = expected_lenses(items)
    fallbacks = {"correctness": ("fb-correctness", ok),
                 "operations": ("fb-operations", ok)}
    report = core.run_verification(
        "diff --git a/app.py b/app.py\n+x = 1\n", providers,
        PREV, "probe", fallbacks=fallbacks, sleep=lambda *a: None)
    recs = [r for r in report["reviewer_reports"]
            if r["provider"] in ("fb-correctness", "fb-operations")]
    assert len(recs) == 1, (seat_names, failing, recs)
    rec = recs[0]
    seat_lenses = lenses[failing]
    # The verification loop tries the seat's lenses in the
    # review path's order and stops at the first fallback that
    # answers: the expected server is the fallback of the
    # FIRST lens of that seat with a fallback configured.
    expected = "fb-" + seat_lenses[0]
    agree = (rec["provider"] == expected
             and rec["fallback_for"] == failing
             and rec["status"] == "ok")
    return lenses, expected, rec, agree


def main():
    lines = [
        "LENS-MAPPING PERMUTATION PROBE — 35dbb7d20941",
        "Claim: verification 'can use a fallback configured for",
        "a different lens than the one originally assigned'.",
        "",
        f"Lenses at HEAD: core.LENSES = {list(core.LENSES)} "
        "(exactly two — the claim's 'more than two lenses in",
        "play' premise does not occur at HEAD.)",
        "",
    ]
    cases = []
    for ordering in itertools.permutations(["seatA", "seatB"]):
        for failing in ordering:
            cases.append((list(ordering), failing))
    cases.append((["onlySeat"], "onlySeat"))
    cases.append((["s0", "s1", "s2"], "s2"))
    cases.append((["s0", "s1", "s2"], "s1"))
    all_agree = True
    for seat_names, failing in cases:
        lenses, expected, rec, agree = run_case(seat_names, failing)
        all_agree = all_agree and agree
        lines.append(
            f"seats={seat_names} failing={failing}: "
            f"assigned lenses={lenses}; fallback served = "
            f"{rec['provider']} (fallback_for={rec['fallback_for']}"
            f", status={rec['status']}); expected for the seat's "
            f"assigned lens = {expected}; AGREE={agree}")
    assert all_agree, "a fallback served a lens it was not " \
                      "configured for"
    lines += [
        "",
        "PROBE OUTCOME: agreement in every case — the serving",
        "fallback is always the one configured for the lens the",
        "failed seat was assigned by the review path's own",
        "mapping (_reviewer_tasks), across orderings, seat",
        "counts, and failing-seat choices. The claim's mechanism",
        "is rebutted at HEAD. Supports the pre-filled",
        "recommendation: sustain refutation, owner ratifies.",
    ]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "lens-mapping-35dbb7d20941.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
