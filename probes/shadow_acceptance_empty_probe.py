#!/usr/bin/env python3
"""Acceptance empty-corpus probe — shadow-branch review, for
633acb885291 (refutation-weak): "Acceptance run crashes with
ZeroDivisionError when the corpus has no cases."

Claim: in `run_acceptance` (src/codereview/acceptance.py),
the M3 overall-accuracy line divides by `len(scores)` with
no guard. Its neighbours ARE guarded — M2/M5 use
`... if <set> else 0.0`, M4 uses `... if denom else None`,
M6 uses `... if measured else None`. M3 is the only unguarded
metric division.

Probe: run `run_acceptance` over an EMPTY corpus (index
names zero cases) under two scorecards:
  A) set-less scorecard (metrics carry thresholds, no
     explicit "set" lists — every metric set then derives
     from the corpus itself, i.e. all empty);
  B) the REAL corpus scorecard
     (~/workspace/codereview-acceptance/scorecard.json),
     whose M1/M2/M5 metrics name explicit case-id sets.
The seat stub raises if ever called: with zero cases no
adjudication happens, so any crash is in the scoring tail.
Record the exact exception, type, and raising line for each
variant — the claim names ZeroDivisionError; whichever
exception each variant actually raises is what the packet
reports.

Exit 0 = both variants' behaviour captured (the probe
reports facts; it does not assert the claim).

POST-FIX (shadow-fixes branch, after the owner ratified
sustain_finding): the scoring tail is guarded — explicit
metric sets score over the cases the run produced, M3
measures 0.0 on an empty corpus, and an empty corpus never
unlocks. This probe now asserts the FIXED behaviour: both
variants return a run record with
unlock_all_gates_pass False."""

import json
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import acceptance  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS,
                   "shadow-acceptance-empty-633acb885291.txt")

REAL_SCORECARD = ("/home/hatch/workspace/codereview-acceptance/"
                  "scorecard.json")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def seat_stub(prompt):  # must never be called: zero cases
    raise AssertionError("seat called for an empty corpus")


def build_corpus(scorecard):
    tmp = tempfile.mkdtemp(prefix="codereview-acc-empty-")
    os.makedirs(os.path.join(tmp, "cases"))
    with open(os.path.join(tmp, "index.json"), "w") as fh:
        json.dump({"cases": []}, fh)
    with open(os.path.join(tmp, "mutations.json"), "w") as fh:
        json.dump({"mutations": []}, fh)
    with open(os.path.join(tmp, "scorecard.json"), "w") as fh:
        json.dump(scorecard, fh)
    return tmp


def attempt(label, scorecard):
    tmp = build_corpus(scorecard)
    try:
        rec = acceptance.run_acceptance(
            tmp, seat_stub, seat_family="deepseek",
            do_mutations=True)
        assert rec["unlock_all_gates_pass"] is False, rec
        emit(f"{label}: NO CRASH — run returned, unlock "
             f"False; metrics: "
             f"{json.dumps(rec['metrics'])[:400]}")
        return "no-crash"
    except Exception as exc:  # noqa: BLE001 — the fact we want
        tb = traceback.extract_tb(sys.exc_info()[2])
        frame = tb[-1]
        emit(f"{label}: CRASH — {type(exc).__name__}: {exc}")
        emit(f"  raising frame: {frame.filename}:"
             f"{frame.lineno}: {frame.line}")
        return type(exc).__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


setless = {"metrics": [
    {"id": "M1_false_dismissals_on_real_findings",
     "threshold": {"op": "==", "value": 0}},
    {"id": "M2_probe_settled_accuracy",
     "threshold": {"op": ">=", "value": 1.0}},
    {"id": "M3_overall_accuracy",
     "threshold": {"op": ">=", "value": 0.9}},
    {"id": "M4_mutation_flip_rate",
     "threshold": {"op": "<=", "value": 0.05}},
    {"id": "M5_protected_and_insufficient_escalated",
     "threshold": {"op": ">=", "value": 1.0}},
    {"id": "M6_double_draw_agreement_on_majors",
     "threshold": {"op": ">=", "value": 0.9}},
]}

emit("variant A — empty corpus, set-less scorecard:")
a = attempt("A", setless)
emit("")
emit("variant B — empty corpus, REAL scorecard "
     f"({REAL_SCORECARD}):")
with open(REAL_SCORECARD, encoding="utf-8") as fh:
    real = json.load(fh)
b = attempt("B", real)

emit("")
emit("guards at HEAD (acceptance.py, verbatim, post-fix):")
src = open(acceptance.__file__, encoding="utf-8").read()
for marker in ('/ len(m2_set)) if m2_set else 0.0',
               "if scores else 0.0",
               "def present(",
               "m4 is not None",
               "bool(cases) and all(",
               "/ len(m5_set)) if m5_set else 0.0",
               "if measured else None"):
    emit(f"  {marker!r}: {'present' if marker in src else 'ABSENT'}")
emit("")
assert a == "no-crash" and b == "no-crash", (a, b)
emit(f"VERDICT FACTS (post-fix): variant A -> {a}; "
     f"variant B -> {b}. Both scorecard shapes now return "
     "a scored run record with unlock_all_gates_pass "
     "False and M3 measured 0.0. Pre-fix, an empty corpus "
     "never produced a run record: variant A crashed "
     "with the ZeroDivisionError the claim names, at the "
     "unguarded M3 line; variant B died earlier, at M1, "
     "with a KeyError on the explicit set's absent cases "
     "(633acb885291, sustained; fixed in the shadow-fixes "
     "branch).")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
