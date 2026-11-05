#!/usr/bin/env python3
"""Closing-B probe — acceptance M4/M6 guards.

Claims:
  60eb09183ee5 (attempt-2, disputed): "M4 mutation flip rate
    has no assertions or guards."
  1f64a6be5c10 (attempt-1, disputed): "M4 denominator zero
    when mutations disabled" (crash / unsafe evaluation).
  e1570280c036 (attempt-2): "M6 double-draw agreement
    division by zero when measured=0."

Method: synthetic mini-corpus (pattern from
tests/test_shadow_acceptance.py) with a scripted seat;
run_acceptance under three shapes:
  A) do_mutations=False (denominator forced to 0 by design);
  B) do_mutations=True but mutations.json names ZERO
     mutations (denominator 0 via len(mutation_ids));
  C) do_mutations=True, normal mutations (control).
For M6: the scripted seat's double draws are made to leave
draws_agree None where possible — and whatever the measured
count is, the M6 block is printed verbatim; a dedicated
zero-measured scenario is forced by monkeypatching
core.shadow_adjudicate to return an entry whose
draws_agree is None (the exact state acceptance.py:334
tests), then re-running the scoring path via run_acceptance.

Writes results/closingB-acceptance-m4m6.txt. Facts only.
"""

import json
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tests"))

from codereview import acceptance, core  # noqa: E402
from test_shadow_acceptance import _case, _payload, _Seat, \
    _write_corpus  # noqa: E402

OUT = os.path.join(HERE, "results", "closingB-acceptance-m4m6.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def run(label, **kw):
    cases = [_case("A1", "sustain_refutation"),
             _case("A2", "sustain_finding")]
    seat = _Seat({"A1": [_payload("sustain_refutation")],
                  "A2": [_payload("sustain_finding",
                                  claim_valid=True)]})
    with tempfile.TemporaryDirectory() as td:
        corpus = os.path.join(td, "corpus")
        _write_corpus(corpus, cases, m1_set=["A2"])
        if kw.pop("empty_mutations", False):
            with open(os.path.join(corpus, "mutations.json"),
                      "w") as fh:
                json.dump({"mutations": []}, fh)
        try:
            rec = acceptance.run_acceptance(
                corpus, seat, seat_family="famC", **kw)
        except Exception:
            say(f"[{label}] RAISED:")
            say(traceback.format_exc())
            return None
        m4 = rec["metrics"]["M4_mutation_flip_rate"]
        m6 = rec["metrics"]["M6_double_draw_agreement_on_majors"]
        say(f"[{label}] returned a record (no exception)")
        say(f"  M4: measured={m4['measured']!r} "
            f"denominator={m4['denominator']} pass={m4['pass']}")
        say(f"  M6: measured={m6['measured']!r} "
            f"measured_cases={m6['measured_cases']} "
            f"majors={m6['majors']} pass={m6['pass']}")
        say(f"  unlock_all_gates_pass={rec['unlock_all_gates_pass']}")
        return rec


def main():
    say("ACCEPTANCE M4/M6 PROBE — 60eb09183ee5, 1f64a6be5c10, "
        "e1570280c036")
    say("code at HEAD: acceptance.py:314-318 (M4 denom/m4), "
        "acceptance.py:327-335 (M6), metrics blocks at "
        "354-373")
    say("")
    run("A do_mutations=False", do_mutations=False)
    say("")
    run("B do_mutations=True, zero mutation ids",
        do_mutations=True, empty_mutations=True)
    say("")
    run("C do_mutations=True, normal (control)",
        do_mutations=True)
    say("")
    # M6 zero-measured forced: shadow_adjudicate stub whose
    # entries carry draws_agree=None (no second draw served).
    say("[D M6 measured=0 forced via stub adjudicator]")
    real = core.shadow_adjudicate

    def stub(seat_fn, finding, region, dispute, **kw):
        return {"decision": "sustain_refutation",
                "severity_after": "major",
                "draws_agree": None, "draws": [],
                "state": "stub", "cache_hit": False}

    core.shadow_adjudicate = stub
    acceptance.core.shadow_adjudicate = stub
    try:
        run("D draws_agree=None on every case",
            do_mutations=False)
    finally:
        core.shadow_adjudicate = real
        acceptance.core.shadow_adjudicate = real
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
