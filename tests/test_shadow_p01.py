"""P0/P1 machinery (four-disputed solution §§4–5): the shadow
reason_check (existence check on cited constructs), the shadow
trace-gate evaluation, and the P1 record schema — reason fields
on refutations and basis-evidence-gated precedent minting."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

SRC = (
    "def compute_total(items):\n"
    "    return sum(items)\n"
    "\n"
    "VALUE = compute_total(items)\n")


class ReasonCheckTests(unittest.TestCase):
    def test_verified_when_cited_construct_exists(self):
        rc = core._reason_check(
            {"reason": "the guard `return sum(items)` handles "
                       "the empty case"}, SRC)
        self.assertEqual(rc["status"], "verified")
        self.assertEqual(rc["found"], ["return sum(items)"])

    def test_contradicted_case4_pattern(self):
        # The Case-4 shape: a guard asserted that exists
        # nowhere in the source.
        rc = core._reason_check(
            {"reason": "safe because `if not tl_name` returns "
                       "early"}, SRC)
        self.assertEqual(rc["status"], "contradicted")
        self.assertEqual(rc["missing"], ["if not tl_name"])

    def test_unverified_without_constructs(self):
        rc = core._reason_check(
            {"reason": "membership works on any object"}, SRC)
        self.assertEqual(rc["status"], "unverified")
        self.assertEqual(rc["cited"], [])

    def test_mixed_is_unverified_with_detail(self):
        rc = core._reason_check(
            {"reason": "`return sum(items)` exists but "
                       "`missing_guard()` does not"}, SRC)
        self.assertEqual(rc["status"], "unverified")
        self.assertEqual(rc["found"], ["return sum(items)"])
        self.assertEqual(rc["missing"], ["missing_guard()"])


class TraceGateShadowTests(unittest.TestCase):
    def _finding(self, **kw):
        f = {"severity": "major", "file": "app.py", "line": 4,
             "evidence": "VALUE = compute_total(items)",
             "evidence_quote": "VALUE = compute_total(items)"}
        f.update(kw)
        return f

    def test_major_callee_claim_without_body_would_downgrade(
            self):
        tg = core._trace_gate_shadow(self._finding(), SRC)
        self.assertTrue(tg["applies"])
        self.assertEqual(tg["about_callee"], ["compute_total"])
        self.assertFalse(tg["callee_body_quoted"])
        self.assertTrue(tg["would_downgrade"])

    def test_body_quote_clears_the_shadow_gate(self):
        tg = core._trace_gate_shadow(self._finding(
            evidence="VALUE = compute_total(items)\n"
                     "return sum(items)"), SRC)
        self.assertTrue(tg["callee_body_quoted"])
        self.assertFalse(tg["would_downgrade"])

    def test_failure_witness_clears_the_shadow_gate(self):
        tg = core._trace_gate_shadow(self._finding(
            failure_witness={"input": "[]",
                             "observed": "KeyError"}), SRC)
        self.assertTrue(tg["failure_witness"])
        self.assertFalse(tg["would_downgrade"])

    def test_minor_does_not_apply(self):
        tg = core._trace_gate_shadow(
            self._finding(severity="minor"), SRC)
        self.assertFalse(tg["applies"])
        self.assertFalse(tg["would_downgrade"])

    def test_callee_not_defined_here_does_not_apply(self):
        tg = core._trace_gate_shadow(
            self._finding(), "VALUE = compute_total(items)\n")
        self.assertFalse(tg["applies"])


class PrecedentBasisTests(unittest.TestCase):
    F = {"id": "f1", "file": "app.py", "line": 2}

    def test_reason_stored_with_verified_basis(self):
        out = core.upsert_precedent(
            [], self.F, "blob1", "r1", "doc.md",
            basis_evidence=[{"file": "app.py", "line": 2,
                             "quote": "return sum(items)"}],
            reason="the refutation is correct",
            reason_origin="model-verified")
        d = out[0]["disposition"]
        self.assertEqual(d["reason"], "the refutation is "
                                      "correct")
        self.assertEqual(d["reason_origin"], "model-verified")
        self.assertEqual(out[0]["basis_evidence"][0]["quote"],
                         "return sum(items)")

    def test_reason_withheld_without_basis(self):
        out = core.upsert_precedent(
            [], self.F, "blob1", "r1", "doc.md",
            reason="safe because `if not tl_name` returns",
            reason_origin="model-verified")
        d = out[0]["disposition"]
        self.assertNotIn("reason", d)
        self.assertEqual(d["reason_withheld"],
                         "basis evidence not verified")

    def test_no_reason_no_withholding_marker(self):
        out = core.upsert_precedent(
            [], self.F, "blob1", "r1", "doc.md")
        self.assertNotIn("reason", out[0]["disposition"])
        self.assertNotIn("reason_withheld",
                         out[0]["disposition"])


# --------------- run-level schema integration ---------------

PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,4 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n"
    "+RESULT = VALUE * 2\n")
CITED = "VALUE = compute_total(items)"
META3 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"},
         "seatC": {"family": "famC", "tier": "paid"}}


class _Seat:
    def __init__(self, review=None, xconfirm=None):
        self.review = review or {"verdict": "pass",
                                 "findings": []}
        self.xconfirm = xconfirm or {"verdict": "confirm"}

    def __call__(self, prompt):
        if "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        elif "RE-GROUND pass" in prompt:
            payload = {"status": "withdrawn", "reason": "x"}
        elif "TECH LEAD ADJUDICATION pass" in prompt:
            payload = {"decision": "escalate",
                       "evidence_quote": "print(VALUE)",
                       "rationale": "owner decides"}
        else:
            payload = self.review
        return payload if isinstance(payload, str) \
            else json.dumps(payload)


class RecordSchemaTests(unittest.TestCase):
    def test_dispute_carries_p1_fields(self):
        finding = {"severity": "major",
                   "category": "correctness", "file": "app.py",
                   "line": 2, "title": "Total without a guard",
                   "evidence": CITED, "evidence_quote": CITED,
                   "recommendation": "guard it",
                   "confidence": 0.9}
        panel = {
            "seatA": _Seat(review={
                "verdict": "changes_requested",
                "findings": [finding]}),
            "seatB": _Seat(xconfirm={
                "verdict": "refute",
                "evidence_quote": "print(VALUE)",
                "reason": "no guard `if not items` exists"}),
            "seatC": _Seat()}
        rec = core.run_review(
            PATCH, panel, seat_meta=META3,
            sleep=lambda *_a: None)
        escalated = rec.get("escalated_findings") or []
        self.assertEqual(len(escalated), 1)
        dispute = escalated[0]["dispute"]
        self.assertIn("reason_check", dispute)
        self.assertIn("reason_corrected", dispute)
        self.assertIsNone(dispute["reason_corrected"])
        self.assertEqual(
            dispute["basis_evidence"][0]["quote"],
            "print(VALUE)")
        self.assertIn("trace_gate_shadow", dispute)
        # The cited construct `if not items` is absent from
        # the blob -> the shadow check says contradicted.
        self.assertEqual(dispute["reason_check"]["status"],
                         "contradicted")
        self.assertEqual(
            len(rec.get("shadow_reason_checks") or []), 1)
        self.assertEqual(
            len(rec.get("shadow_trace_gate") or []), 1)


if __name__ == "__main__":
    unittest.main()
