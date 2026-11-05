#!/usr/bin/env python3
"""Closing-B probe — bench.py cluster.

Claims:
  e8c5d3fd8a25 (attempt-1, disputed): missing/non-numeric
    confidence crashes the scoring sort in score_case.
  5e89ea2d985b (attempt-1): severity ordering is reversed in
    matching, so lower-severity findings steal matches from
    blockers/majors.
  55752b0dc5b7 (attempt-2): forced reruns are rejected
    whenever ANY old stored record was degraded, even when
    the new run is healthy.

Writes results/closingB-bench.txt. Facts only.
"""

import json
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import bench  # noqa: E402

OUT = os.path.join(HERE, "results", "closingB-bench.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def conf_probe():
    say("== e8c5d3fd8a25: score_case confidence handling "
        "(bench.py:226-231) ==")
    case = {"id": "c1", "expected": [
        {"severity": "major", "file": "a.py", "line": 3,
         "title": "null deref in handler", "category": "correctness",
         "keywords": []}]}
    base = {"severity": "major", "file": "a.py", "line": 3,
            "title": "null deref in handler",
            "category": "correctness"}
    for label, extra in [("confidence=None", {"confidence": None}),
                         ("confidence missing", {}),
                         ("confidence='high'", {"confidence": "high"}),
                         ("confidence=0.9 (control)",
                          {"confidence": 0.9})]:
        f = dict(base, **extra)
        try:
            r = bench.score_case(case, [f])
            say(f"  {label}: OK — matched={r['matched']} "
                f"escaped={r['escaped']}")
        except Exception as exc:
            say(f"  {label}: RAISED {type(exc).__name__}: {exc}")


def sev_probe():
    say("")
    say("== 5e89ea2d985b: severity order in matching "
        "(bench.py:226-257; core._SEV_RANK from SEVERITIES "
        "('blocker','major','minor','nit') at core.py:56-57) ==")
    # One expected BLOCKER defect; TWO findings match it
    # textually — a minor listed FIRST in the input and a
    # blocker second. If ordering were reversed (minor first),
    # the minor steals the match and the defect row records
    # escaped=True (minor is not gate-blocking).
    case = {"id": "c2", "expected": [
        {"severity": "blocker", "file": "a.py", "line": 3,
         "title": "sql injection in login", "category": "security",
         "keywords": []}]}
    minor = {"severity": "minor", "file": "a.py", "line": 3,
             "title": "sql injection in login",
             "category": "security", "confidence": 0.99}
    blocker = {"severity": "blocker", "file": "a.py", "line": 3,
               "title": "sql injection in login",
               "category": "security", "confidence": 0.1}
    r = bench.score_case(case, [minor, blocker])
    row = r["defects"][0]
    say(f"  input order [minor, blocker]; matched finding "
        f"severity={row['finding_severity']!r} "
        f"escaped={row['escaped']} matched={row['matched']}")
    say(f"  false_positives={r['false_positives']} "
        f"(the unmatched finding is counted as an FP)")


CLEAN_DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def _pass(_prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def _boom(_prompt):
    raise RuntimeError("provider down")


def force_probe():
    say("")
    say("== 55752b0dc5b7: bench --force degraded check "
        "(bench.py:484-586) ==")
    with tempfile.TemporaryDirectory() as td:
        corpus = os.path.join(td, "corpus")
        cdir = os.path.join(corpus, "clean-one")
        os.makedirs(cdir)
        os.makedirs(os.path.join(td, "configs"))
        os.makedirs(os.path.join(td, "scripts"))
        meta = {"id": "clean-one", "title": "case clean-one",
                "category": "clean", "split": "public",
                "source": "closingB fixture", "license": "MIT",
                "expected": []}
        with open(os.path.join(cdir, "case.json"), "w") as fh:
            json.dump(meta, fh)
        with open(os.path.join(cdir, "diff.patch"), "w") as fh:
            fh.write(CLEAN_DIFF)
        with open(os.path.join(td, "scripts", "oracle.json"),
                  "w") as fh:
            json.dump({"default": {"verdict": "pass",
                                   "summary": "nothing",
                                   "findings": []}}, fh)
        with open(os.path.join(td, "configs", "oracle.json"),
                  "w") as fh:
            json.dump({"name": "oracle",
                       "providers": [{"name": "oracle",
                                      "script": "../scripts/oracle.json"}]},
                      fh)
        out = os.path.join(td, "out")
        healthy = {"oracle": {"ok": _pass}}
        bench.run_bench(corpus, ["oracle"], out,
                        providers_by_config=healthy)
        path = os.path.join(out, "oracle.jsonl")
        with open(path) as fh:
            stored = [json.loads(x) for x in fh if x.strip()]
        stored[0]["degraded"] = True
        with open(path, "w") as fh:
            fh.write(json.dumps(stored[0]) + "\n")
        say("  stored file seeded: sole record degraded=true "
            "(resume hashes untouched)")
        try:
            results = bench.run_bench(
                corpus, ["oracle"], out, force=True,
                providers_by_config=healthy)
            with open(path) as fh:
                after = [json.loads(x) for x in fh if x.strip()]
            say(f"  forced HEALTHY rerun over old degraded "
                f"record: ACCEPTED — returned "
                f"{len(results['oracle'])} record(s); file "
                f"holds {len(after)}, degraded="
                f"{after[0]['degraded']}")
        except ValueError as exc:
            say(f"  forced HEALTHY rerun: REFUSED — {exc}")
        with open(path) as fh:
            before = fh.read()
        try:
            bench.run_bench(corpus, ["oracle"], out, force=True,
                            providers_by_config={
                                "oracle": {"bad": _boom}})
            say("  forced DEGRADED rerun: ACCEPTED (control "
                "failed — guard missing)")
        except ValueError as exc:
            say(f"  forced DEGRADED rerun (control): REFUSED — "
                f"{str(exc)[:120]}")
        with open(path) as fh:
            say(f"  previous file intact after refusal: "
                f"{fh.read() == before}")


def main():
    say("BENCH PROBE — e8c5d3fd8a25, 5e89ea2d985b, 55752b0dc5b7")
    try:
        conf_probe()
    except Exception:
        say(traceback.format_exc())
    sev_probe()
    force_probe()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
