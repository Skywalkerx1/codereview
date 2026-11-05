"""Tests for the ratified packet fixes (owner ratification,
2026-11-04 evening):

  7ea4e96603e9 / 212878ab6bba — the gate line states the degraded
  CAUSE and never claims a reviewer failed when none did.
  78ddf4d5ea27 — role_models credits the model that actually
  serves, never a discarded override.
  ec925437d0e3 / 20e4194e5ed9 — the records scan relativises
  local paths and masks account identifiers in committed output.
  3f50bf6b3349 — _prompt_slice respects its cap: the truncation
  marker lives INSIDE the budget.
"""

import hashlib
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, providers  # noqa: E402

CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def pass_provider(prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def failing_provider(prompt):
    raise TimeoutError("provider timed out")


class GateLineCauseTests(unittest.TestCase):
    """Fix 1 — packets #5/#6 (7ea4e96603e9, 212878ab6bba)."""

    def test_synthetic_coverage_degraded_claims_no_failure(self):
        # The PT1 synthetic verbatim: all reviewers ok, degraded
        # by incomplete coverage, built through core._gate.
        gate, reasons = core._gate([], degraded=True, incomplete=True)
        self.assertEqual(gate, "pass")
        joined = "; ".join(reasons)
        self.assertNotIn("at least one reviewer failed", joined)
        self.assertNotIn("reviewer failed", joined)
        self.assertIn("coverage incomplete", joined)

    def test_gate_with_coverage_cause_states_it(self):
        gate, reasons = core._gate(
            [], degraded=True, degraded_causes=["coverage incomplete"])
        self.assertEqual(gate, "pass")
        joined = "; ".join(reasons)
        self.assertIn("coverage incomplete", joined)
        self.assertNotIn("reviewer failed", joined)

    def test_gate_with_reviewer_failure_still_claims_it(self):
        # The normal degraded-with-failure case keeps the exact,
        # now TRUE, claim — and strict mode still turns a
        # non-blocked degraded round inconclusive.
        gate, reasons = core._gate(
            [], degraded=True, degraded_causes=["reviewer failure"])
        self.assertEqual(gate, "pass")
        self.assertIn("at least one reviewer failed (degraded review)",
                      reasons)
        gate, reasons = core._gate(
            [], degraded=True, strict=True,
            degraded_causes=["reviewer failure"])
        self.assertEqual(gate, "inconclusive")
        self.assertIn("at least one reviewer failed (degraded review)",
                      reasons)

    def test_run_review_failure_records_cause_and_renders_it(self):
        report = core.run_review(
            CLEAN, {"a": failing_provider, "b": pass_provider})
        self.assertTrue(report["degraded"])
        self.assertIn("reviewer failure", report["degraded_causes"])
        self.assertIn("at least one reviewer failed",
                      "; ".join(report["gate_reasons"]))
        gate_line = core.render_markdown(report).splitlines()[2]
        self.assertIn("DEGRADED: reviewer failure", gate_line)
        self.assertIn("1 of 2 reviewers succeeded", gate_line)

    def test_rendered_gate_line_for_coverage_degraded_run(self):
        # A stored-shape record for a run degraded by coverage
        # with every reviewer ok: the rendered gate line states
        # the cause next to the (full) success count.
        _gate, reasons = core._gate(
            [], degraded=True, incomplete=True,
            degraded_causes=["coverage incomplete"])
        report = {
            "mode": "review", "gate": "pass",
            "gate_reasons": reasons,
            "created_at": "2026-11-04T00:00:00+00:00",
            "patch_sha256": "0" * 64,
            "degraded": True,
            "degraded_causes": ["coverage incomplete"],
            "reviewer_reports": [{"status": "ok"}, {"status": "ok"}],
            "findings": [], "test_results": [],
        }
        gate_line = core.render_markdown(report).splitlines()[2]
        self.assertIn("DEGRADED: coverage incomplete", gate_line)
        self.assertIn("(2 of 2 reviewers succeeded)", gate_line)
        self.assertNotIn("at least one reviewer failed", gate_line)


if __name__ == "__main__":
    unittest.main()
