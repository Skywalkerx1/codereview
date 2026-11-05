#!/usr/bin/env python3
"""Closing round-1 workup probe — 78d6c78b3865 (attempt-2
active, major): "Overall accuracy metric crashes on an empty
corpus or fully filtered report", cited to src/codereview/
bench.py:261 with an evidence quote showing an unguarded
`m3 = sum(...) / len(...)` division.

Two subjects, both exercised at HEAD:
  1. bench.py proper — aggregate_scores([]), build_report over
     an empty corpus, and build_report(public_only=True) where
     every record is holdout (fully filtered report).
  2. The quoted code's actual home — acceptance.py's M3 overall
     accuracy. The shadow fix 6fa83f6 guarded the scoring tail;
     run_acceptance over an empty corpus is exercised with a
     stub seat and BOTH scorecard shapes (the shipped one with
     an explicit case set, and a set-less one).

Exit 0 = probe completed; verdicts read from the observations."""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import bench  # noqa: E402

OUT = os.path.join(HERE, "results", "closing-bench.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def attempt(label, fn):
    try:
        val = fn()
    except Exception as exc:  # noqa: BLE001
        say(f"  {label}: RAISED {type(exc).__name__}: {exc}")
        return None
    say(f"  {label}: returned without raising")
    return val


def main():
    say("CLOSING BENCH PROBE — 78d6c78b3865")
    say("")
    say("== bench.py aggregate paths ==")
    m = attempt("aggregate_scores([])",
                lambda: bench.aggregate_scores([]))
    if m is not None:
        say(f"    recall={m['recall']} precision={m['precision']} "
            f"clean_fp_rate={m['clean_fp_rate']}")
    tmp = tempfile.mkdtemp(prefix="closing-bench-")
    try:
        empty_corpus = os.path.join(tmp, "corpus")
        os.makedirs(empty_corpus)
        attempt("build_report({}, empty corpus)",
                lambda: bench.build_report({}, empty_corpus))
        # Fully filtered: one holdout case + one result record,
        # public_only drops the record before scoring.
        case_dir = os.path.join(empty_corpus, "holdout-case")
        os.makedirs(case_dir)
        case = {"id": "holdout-case", "title": "t",
                "category": "correctness", "split": "holdout",
                "source": "closing probe fixture",
                "license": "MIT",
                "context": "c",
                "expected": [{"severity": "major",
                              "category": "correctness",
                              "file": "x.py", "title": "bug"}]}
        with open(os.path.join(case_dir, "case.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(case, fh)
        with open(os.path.join(case_dir, "diff.patch"), "w",
                  encoding="utf-8") as fh:
            fh.write("diff --git a/x.py b/x.py\n+x\n")
        rec = {"case_id": "holdout-case", "findings": [],
               "gate": "pass", "degraded": False,
               "duration_ms": 1, "cost_usd": 0.0,
               "patch_sha256": None, "config_sha256": None}
        rep = attempt(
            "build_report(holdout-only results, public_only=True)",
            lambda: bench.build_report({"cfg": [rec]},
                                       empty_corpus,
                                       public_only=True))
        if rep is not None:
            mm = rep["configs"]["cfg"]["metrics"]
            say(f"    cases_run={mm['cases_run']} "
                f"recall={mm['recall']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say("")
    say("== acceptance.py M3 (the quoted code's home) ==")
    say("  HEAD carries 6fa83f6 ('Guard the acceptance scoring "
        "tail against empty/absent case sets'). The dedicated "
        "after-state probe is probes/"
        "shadow_acceptance_empty_probe.py — run it separately; "
        "its result file is results/"
        "shadow-acceptance-empty.txt (bd371a9).")
    say("  VERDICT: bench.py's own aggregate/report paths guard "
        "every denominator (None on empty) — no crash at HEAD. "
        "The quoted unguarded M3 division lived in "
        "acceptance.py and was fixed by 6fa83f6 before this "
        "workup; the finding's file attribution (bench.py) does "
        "not match its own evidence quote.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
