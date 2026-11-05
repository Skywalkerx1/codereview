"""Shadow Tech Lead (refutation-process solution Q2/Q4):
the full structured adjudication in shadow mode — blinded
A/B positions, double-draw for majors, reduced-independence
pending state, decision cache, probe round — and the
cardinal invariant: shadow decisions NEVER change the gate."""

import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

REGION = ("import os\n"
          "VALUE = compute_total(items)\n"
          "print(VALUE)\n"
          "RESULT = VALUE * 2\n")
FINDING = {"id": "fx1", "file": "app.py", "line": 2,
           "severity": "major", "title": "Total without guard",
           "evidence": "VALUE = compute_total(items)",
           "evidence_quote": "VALUE = compute_total(items)"}
DISPUTE = {"by": "seatB", "family": "famB",
           "raiser_family": "famA",
           "evidence_quote": "print(VALUE)",
           "reason": "the claim fails on the printed value"}


def payload(decision="sustain_refutation", quote="print(VALUE)",
            **over):
    p = {"claim_restated": "the total lacks a guard",
         "claim_falsifiable": True,
         "position_a_addresses_claim": {"value": True,
                                        "why": "a addresses"},
         "position_b_addresses_claim": {"value": False,
                                        "why": "b misses"},
         "reasoning_assessment": {
             "claim_valid": False,
             "refutation_validity": "valid"},
         "deciding_evidence": {"quote": quote},
         "probe_request": None,
         "decision": decision,
         "severity_after_rubric": {"level": "major",
                                   "rubric_clause": None},
         "confidence": "high",
         "rationale": "the code shows it"}
    p.update(over)
    return p


class ShadowSeat:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


def adjudicate(seat, **kw):
    kw.setdefault("seat_name", "tl")
    kw.setdefault("seat_family", "famC")
    return core.shadow_adjudicate(
        seat, dict(FINDING), REGION, dict(DISPUTE), **kw)


class ShadowDecisionTests(unittest.TestCase):
    def test_major_dismissal_double_draw_agrees(self):
        seat = ShadowSeat([payload(), payload()])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "shadow_sustained_refutation")
        self.assertEqual(e["decision"], "sustain_refutation")
        self.assertTrue(e["draws_agree"])
        self.assertEqual(len(e["draws"]), 2)
        self.assertFalse(e["binding"])
        self.assertEqual(
            e["deciding_evidence"]["quote"], "print(VALUE)")
        self.assertTrue(e["cache_key"])
        self.assertEqual(e["protocol_version"],
                         core.ADJUDICATION_PROTOCOL_VERSION)

    def test_double_draw_disagreement_escalates(self):
        seat = ShadowSeat([
            payload(),
            payload(decision="sustain_finding",
                    quote="VALUE = compute_total(items)")])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "shadow_escalated")
        self.assertFalse(e["draws_agree"])
        self.assertIsNone(e["decision"])

    def test_reduced_independence_dismissal_is_pending(self):
        seat = ShadowSeat([payload(), payload()])
        e = adjudicate(seat, independence="reduced")
        self.assertEqual(e["state"],
                         "adjudication-pending-independence")
        # The decision is recorded, marked non-effective.
        self.assertEqual(e["decision"], "sustain_refutation")

    def test_reduced_independence_sustain_stands(self):
        seat = ShadowSeat([
            payload(decision="sustain_finding",
                    quote="VALUE = compute_total(items)"),
            payload(decision="sustain_finding",
                    quote="VALUE = compute_total(items)")])
        e = adjudicate(seat, independence="reduced")
        self.assertEqual(e["state"], "shadow_sustained_finding")

    def test_unvalidated_deciding_quote_escalates(self):
        seat = ShadowSeat([
            payload(quote="a line that is nowhere"), payload(
                quote="a line that is nowhere")])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "shadow_escalated")
        self.assertIn("deciding quote", e["error"] or "")

    def test_severity_change_needs_a_clause(self):
        bad = payload(severity_after_rubric={
            "level": "minor", "rubric_clause": None})
        e = adjudicate(ShadowSeat([bad, bad]))
        self.assertEqual(e["state"], "shadow_escalated")
        good = payload(severity_after_rubric={
            "level": "minor", "rubric_clause": "R3"})
        e2 = adjudicate(ShadowSeat([good, good]))
        self.assertEqual(e2["state"],
                         "shadow_sustained_refutation")
        self.assertEqual(
            e2["severity_after_rubric"],
            {"level": "minor", "rubric_clause": "R3"})

    def test_probe_round_then_decision(self):
        calls = []

        def probe_fn(finding, request):
            calls.append((finding, request))
            return {"status": "supported",
                    "detail": "probe output",
                    "evidence_quote": "probe output"}

        seat = ShadowSeat([
            payload(decision="needs_probe",
                    probe_request={"kind": "python",
                                   "code": "print(1)"}),
            payload(), payload()])
        e = adjudicate(seat, probe_fn=probe_fn)
        self.assertEqual(len(calls), 1)
        # The documented contract: probe_fn(finding, request).
        self.assertEqual(calls[0][0]["id"], FINDING["id"])
        self.assertIn('"python"', calls[0][1])
        self.assertEqual(e["probe_result"]["status"],
                         "supported")
        self.assertEqual(e["state"],
                         "shadow_sustained_refutation")
        self.assertEqual(len(e["draws"]), 3)

    def test_probe_round_through_production_wiring(self):
        # Regression for 833912a09fa3: the shadow probe round
        # driven through the REAL harness (probe.make_probe_fn,
        # the CLI's default wiring) must actually EXECUTE the
        # spec — the old one-arg call swallowed a TypeError
        # into a "probe failed" record and the spec never ran.
        import tempfile

        from codereview import probe as probe_mod

        seat = ShadowSeat([
            payload(decision="needs_probe",
                    probe_request={
                        "kind": "python",
                        "code": "print('PROBE_EXECUTED_MARKER')"}),
            payload(), payload()])
        with tempfile.TemporaryDirectory() as tree:
            e = adjudicate(
                seat, probe_fn=probe_mod.make_probe_fn(
                    tree, timeout=30))
        pr = e["probe_result"]
        self.assertEqual(pr["outcome"], "pass")
        self.assertIn("PROBE_EXECUTED_MARKER", pr["output"])
        self.assertEqual(e["state"],
                         "shadow_sustained_refutation")

    def test_miswired_probe_fn_is_not_probe_evidence(self):
        # A callable that does not implement the two-arg
        # contract (the pre-fix suite stub's shape) must be
        # recorded as a WIRING error — distinguishable from,
        # and never readable as, a probe result.
        def one_arg_stub(spec_text):  # the old broken shape
            return {"status": "supported",
                    "detail": "probe output"}

        seat = ShadowSeat([
            payload(decision="needs_probe",
                    probe_request={"kind": "python",
                                   "code": "print(1)"}),
            payload(), payload()])
        e = adjudicate(seat, probe_fn=one_arg_stub)
        pr = e["probe_result"]
        self.assertEqual(pr["status"], "wiring_error")
        self.assertFalse(pr["can_rebut"])
        self.assertFalse(pr["can_support"])
        self.assertIn("wiring", pr["detail"])

    def test_needs_probe_without_channel_escalates(self):
        seat = ShadowSeat([payload(
            decision="needs_probe",
            probe_request={"kind": "python", "code": "x"})])
        e = adjudicate(seat)
        self.assertEqual(e["state"], "shadow_escalated")
        self.assertIn("needs_probe", e["error"] or "")

    def test_cache_hit_makes_no_second_call(self):
        seat = ShadowSeat([payload()])
        cache = {}
        minor = dict(FINDING, severity="minor")
        e1 = core.shadow_adjudicate(
            seat, minor, REGION, dict(DISPUTE), cache=cache,
            seat_name="tl", seat_family="famC")
        e2 = core.shadow_adjudicate(
            seat, minor, REGION, dict(DISPUTE), cache=cache,
            seat_name="tl", seat_family="famC")
        self.assertFalse(e1["cache_hit"])
        self.assertTrue(e2["cache_hit"])
        self.assertEqual(len(seat.prompts), 1)
        self.assertEqual(e1["cache_key"], e2["cache_key"])

    def test_blinding_strips_families(self):
        seat = ShadowSeat([payload()])
        adjudicate(seat)
        prompt = seat.prompts[0]
        self.assertNotIn("famA", prompt)
        self.assertNotIn("famB", prompt)
        self.assertIn("POSITION A", prompt)
        self.assertIn("POSITION B", prompt)

    def test_no_seat_is_unavailable_not_a_decision(self):
        e = core.shadow_adjudicate(
            None, dict(FINDING), REGION, dict(DISPUTE))
        self.assertEqual(e["state"], "shadow_unavailable")
        self.assertIsNone(e["decision"])


# --------------- gate invariance under shadow ---------------

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


class PanelSeat:
    def __init__(self, review=None, xconfirm=None):
        self.review = review or {"verdict": "pass",
                                 "findings": []}
        self.xconfirm = xconfirm or {"verdict": "confirm"}

    def __call__(self, prompt):
        if "SHADOW MODE" in prompt:
            p = payload()
        elif "TECH LEAD ADJUDICATION pass" in prompt:
            p = {"decision": "sustain_refutation",
                 "evidence_quote": "print(VALUE)",
                 "rationale": "binding decision"}
        elif "CROSS-FAMILY CONFIRMATION pass" in prompt:
            p = self.xconfirm
        elif "RE-GROUND pass" in prompt:
            p = {"status": "withdrawn", "reason": "x"}
        else:
            p = self.review
        return p if isinstance(p, str) else json.dumps(p)


def _panel():
    finding = {"severity": "major", "category": "correctness",
               "file": "app.py", "line": 2,
               "title": "Total computed without a guard",
               "evidence": CITED, "evidence_quote": CITED,
               "recommendation": "guard it", "confidence": 0.9}
    return {
        "seatA": PanelSeat(review={
            "verdict": "changes_requested",
            "findings": [finding]}),
        "seatB": PanelSeat(xconfirm={
            "verdict": "refute",
            "evidence_quote": "print(VALUE)",
            "reason": "the claim is wrong"}),
        "seatC": PanelSeat()}


LIST_KEYS = ("blocker_findings", "major_findings",
             "disputed_findings", "refutation_weak_findings",
             "adjudicated_refuted_findings",
             "escalated_findings", "findings")


class GateInvarianceTests(unittest.TestCase):
    def _run(self, **kw):
        kw.setdefault("seat_meta", META3)
        kw.setdefault("sleep", lambda *_a: None)
        return core.run_review(PATCH, _panel(), **kw)

    def test_shadow_on_off_verdicts_identical(self):
        off = self._run()
        on = self._run(tech_lead_shadow=True)
        self.assertEqual(off["gate"], on["gate"])
        for key in LIST_KEYS:
            off_ids = [f.get("id") for f in off.get(key) or []]
            on_ids = [f.get("id") for f in on.get(key) or []]
            self.assertEqual(off_ids, on_ids, key)
        self.assertNotIn("shadow_adjudications", off)
        entries = on.get("shadow_adjudications") or []
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["binding"])
        self.assertEqual(
            entries[0]["state"], "shadow_sustained_refutation")
        # Finding-level dispositions are byte-identical apart
        # from the shadow annotation itself.
        def strip(rec):
            out = []
            for key in LIST_KEYS:
                for f in rec.get(key) or []:
                    g = {k: v for k, v in f.items()
                         if k != "tech_lead_shadow"}
                    out.append((key, json.dumps(
                        g, sort_keys=True, default=str)))
            return sorted(out)
        self.assertEqual(strip(off), strip(on))
        refuted = on["adjudicated_refuted_findings"][0]
        self.assertEqual(
            refuted["tech_lead_shadow"]["binding"], False)


if __name__ == "__main__":
    unittest.main()
