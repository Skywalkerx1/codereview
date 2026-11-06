"""D-001 (external Phase 0–1 test report, 2026-11-06):
identical inputs produced non-identical records across runs.

Root cause: run_review's _run_jobs folded reviewer results
into the shared accumulators (reviewer_reports, all_findings)
in as_completed order — i.e. completion order, which varies
run to run. reviewer_reports order varied; merge_findings
builds each merged finding's `sources` in encounter order
over all_findings, so sources order varied too; the markdown
render inherits both. Gate verdicts were always stable.

Fix: _run_jobs collects every result first, then folds them
in SUBMISSION (task) order — the collect-then-order pattern
run_verification already used.

This test runs an identical 4-seat review 8 times with
per-seat delays engineered to reverse completion order
against submission order, and requires the canonical records
(volatile timing fields excluded: created_at, duration_ms,
seat-state at_ms, record_identity) and the markdown renders
to be byte-identical across all runs.
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

PATCH = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

SHARED = {
    "severity": "major", "category": "correctness",
    "file": "app/util.py", "line": 5,
    "title": "sub subtracts the operands in the wrong order",
    "evidence": "return a - b",
    "evidence_quote": "return a - b",
    "recommendation": "return b - a where the caller expects "
                      "the difference the other way",
    "confidence": 0.9}

UNIQUES = {
    "s0": {
        "severity": "minor", "category": "correctness",
        "file": "app/util.py", "line": 2,
        "title": "add overflows silently for huge integers",
        "evidence": "return a + b",
        "evidence_quote": "return a + b",
        "recommendation": "document the overflow behaviour",
        "confidence": 0.5},
    "s1": {
        "severity": "minor", "category": "correctness",
        "file": "app/util.py", "line": 2,
        "title": "add lacks type checking on inputs",
        "evidence": "return a + b",
        "evidence_quote": "return a + b",
        "recommendation": "validate operand types",
        "confidence": 0.5},
    "s2": {
        "severity": "minor", "category": "correctness",
        "file": "app/util.py", "line": 5,
        "title": "sub mishandles negative operands quietly",
        "evidence": "return a - b",
        "evidence_quote": "return a - b",
        "recommendation": "document negative-operand handling",
        "confidence": 0.5},
    "s3": {
        "severity": "minor", "category": "correctness",
        "file": "app/util.py", "line": 1,
        "title": "module exposes helpers without documentation",
        "evidence": "def add(a, b):",
        "evidence_quote": "def add(a, b):",
        "recommendation": "add module documentation",
        "confidence": 0.5},
}

SEATS = ("s0", "s1", "s2", "s3")
# Submission order is s0..s3; the delays reverse it, so the
# LAST submitted seat finishes FIRST on every run.
DELAYS = {"s0": 0.24, "s1": 0.16, "s2": 0.08, "s3": 0.0}

VOLATILE_KEYS = ("created_at", "duration_ms", "at_ms")


def _seat(name):
    def serve(prompt):
        time.sleep(DELAYS[name])
        return json.dumps({
            "summary": f"{name} reviewed the change",
            "findings": [dict(SHARED), dict(UNIQUES[name])]})
    return serve


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items()
                if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _canonical(report):
    out = _strip(report)
    out.pop("record_identity", None)
    return json.dumps(out, sort_keys=True, ensure_ascii=False)


class DeterministicRecordTests(unittest.TestCase):
    def test_identical_inputs_identical_records(self):
        providers = {name: _seat(name) for name in SEATS}
        canons = set()
        renders = set()
        last = None
        for _ in range(8):
            report = core.run_review(PATCH, providers)
            canon = _canonical(report)
            canons.add(canon)
            renders.add(core.render_markdown(json.loads(canon)))
            last = json.loads(canon)
        self.assertEqual(len(canons), 1,
                         "records differ across identical runs")
        self.assertEqual(len(renders), 1,
                         "markdown renders differ across runs")
        # Submission order, not completion order, on the record.
        self.assertEqual(
            [r["provider"] for r in last["reviewer_reports"]],
            list(SEATS))
        shared = [f for f in last["findings"]
                  if f["title"] == SHARED["title"]]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["sources"], list(SEATS))
        self.assertEqual(last["gate"], "blocked")


if __name__ == "__main__":
    unittest.main()
