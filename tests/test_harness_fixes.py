"""Harness fixes from the step-2 forensics (Part A) of the
honest-negatives solution — two defects worth fixing
regardless of the Tech Lead seat question, because they
protect the HUMAN gate's evidence too:

FIX 1 (L06): deciding-quote validation checked EXISTENCE
only. A dismissal whose deciding quote was byte-identical
to the refutation's own quote — the disputed line itself —
and silent on the claim's crux passed validation. A
dismissal's deciding quote must now also be DISTINCT from
the refutation's quote (whitespace-normalised) and pass a
deterministic relevance screen against the CLAIM; failing
either makes the dismissal evidence-ineligible (it
escalates), never silently sustained. The acceptance scorer
applies the same check.

FIX 2 (P06): region location anchored purely on evidence
fragments landed on a sibling call site that already had
the fix, ~340 lines from the finding's cited line — the
case was near-unwinnable as presented. Location must now
prefer the region containing the finding's cited line, and
when the cited line cannot be placed, the input is marked
`region_unverified` loudly in the produced record instead
of presenting a confident wrong region."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import acceptance, core  # noqa: E402


# ------------------------- FIX 1: shadow draws -------------------------

REGION = ("import signal\n"
          "VALUE = compute_total(items)\n"
          "RESULT = VALUE * 2\n"
          "print(VALUE)\n")
FINDING = {"id": "hx1", "file": "app.py", "line": 2,
           "severity": "major",
           "title": "compute_total result is never bounded "
                    "before use",
           "evidence": "VALUE = compute_total(items) is used "
                       "unbounded as the total",
           "evidence_quote": "VALUE = compute_total(items)"}
DISPUTE = {"by": "seatB", "family": "famB",
           "raiser_family": "famA",
           "evidence_quote": "print(VALUE)",
           "reason": "the claim fails on the printed value"}


def _payload(decision="sustain_refutation",
             quote="RESULT = VALUE * 2"):
    return {"claim_restated": "the total is never bounded",
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


class _Seat:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def __call__(self, prompt):
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


def _adjudicate(seat, finding=None, dispute=None):
    return core.shadow_adjudicate(
        seat, dict(finding or FINDING), REGION,
        dict(dispute or DISPUTE), seat_name="tl",
        seat_family="famC")


class DismissalQuoteCheckUnitTests(unittest.TestCase):
    CLAIM = ("compute_total result is never bounded before "
             "use\nVALUE = compute_total(items) is used "
             "unbounded as the total")

    def test_identical_to_refuter_quote_is_ineligible(self):
        check = core._dismissal_quote_check(
            "print(VALUE)", "print(VALUE)", self.CLAIM)
        self.assertFalse(check["eligible"])
        self.assertFalse(check["distinct"])

    def test_whitespace_variant_of_refuter_quote_is_ineligible(self):
        check = core._dismissal_quote_check(
            "  print(VALUE)  ", "print(VALUE)", self.CLAIM)
        self.assertFalse(check["eligible"])
        self.assertFalse(check["distinct"])

    def test_unrelated_quote_is_ineligible(self):
        check = core._dismissal_quote_check(
            "import signal", "print(VALUE)", self.CLAIM)
        self.assertFalse(check["eligible"])
        self.assertTrue(check["distinct"])
        self.assertFalse(check["relevant"])

    def test_distinct_relevant_quote_is_eligible(self):
        check = core._dismissal_quote_check(
            "RESULT = VALUE * 2", "print(VALUE)", self.CLAIM)
        self.assertTrue(check["eligible"])
        self.assertTrue(check["distinct"])
        self.assertTrue(check["relevant"])

    def test_empty_refuter_quote_cannot_fail_distinctness(self):
        check = core._dismissal_quote_check(
            "RESULT = VALUE * 2", "", self.CLAIM)
        self.assertTrue(check["distinct"])
        self.assertTrue(check["eligible"])


class DismissalEligibilityDrawTests(unittest.TestCase):
    def test_self_quote_dismissal_escalates(self):
        # The L06 shape: the deciding quote IS the refuter's
        # quote (the disputed line itself).
        seat = _Seat([_payload(quote="print(VALUE)"),
                      _payload(quote="print(VALUE)")])
        e = _adjudicate(seat)
        self.assertEqual(e["state"], "shadow_escalated")
        self.assertIsNone(e["decision"])
        self.assertIn("dismissal-evidence rule",
                      e["error"] or "")
        draw = e["draws"][0]
        self.assertFalse(
            draw["deciding_quote_check"]["distinct"])
        self.assertFalse(
            draw["deciding_quote_check"]["eligible"])

    def test_unrelated_quote_dismissal_escalates(self):
        seat = _Seat([_payload(quote="import signal"),
                      _payload(quote="import signal")])
        e = _adjudicate(seat)
        self.assertEqual(e["state"], "shadow_escalated")
        self.assertIsNone(e["decision"])
        self.assertIn("dismissal-evidence rule",
                      e["error"] or "")
        draw = e["draws"][0]
        self.assertTrue(
            draw["deciding_quote_check"]["distinct"])
        self.assertFalse(
            draw["deciding_quote_check"]["relevant"])

    def test_distinct_relevant_dismissal_still_sustains(self):
        seat = _Seat([_payload(), _payload()])
        e = _adjudicate(seat)
        self.assertEqual(e["state"],
                         "shadow_sustained_refutation")
        self.assertEqual(e["decision"], "sustain_refutation")
        self.assertTrue(
            e["draws"][0]["deciding_quote_check"]["eligible"])

    def test_sustain_finding_is_not_a_dismissal(self):
        # The dismissal rule must not leak onto sustains: a
        # sustain may rest on the finding's own cited line.
        seat = _Seat([
            _payload(decision="sustain_finding",
                     quote="VALUE = compute_total(items)"),
            _payload(decision="sustain_finding",
                     quote="VALUE = compute_total(items)")])
        e = _adjudicate(seat)
        self.assertEqual(e["state"], "shadow_sustained_finding")


class DismissalScorerTests(unittest.TestCase):
    def _case(self):
        return {"case_id": "HX", "case_class": "synthetic",
                "title": "HX",
                "finding": {
                    "claim": "compute_total result is never "
                             "bounded before use",
                    "evidence": "VALUE = compute_total(items) "
                                "is used unbounded as the total",
                    "evidence_quote":
                        "VALUE = compute_total(items)",
                    "severity_as_raised": "major",
                    "file": "app.py", "line": 2,
                    "raised_by_family": "famA"},
                "refutation": {"by_family": "famB",
                               "quote": "print(VALUE)",
                               "reason": "the claim is wrong"},
                "code_region": {"path": "app.py",
                                "start_line": 1, "end_line": 4,
                                "text": REGION},
                "probe": None,
                "expected": {"decision": "escalate",
                             "severity_after": None,
                             "scoring":
                                 "dismissal_evidence_rule"}}

    def _entry(self, quote):
        return {"decision": "sustain_refutation",
                "deciding_evidence": {"quote": quote},
                "severity_after_rubric": {"level": "major"}}

    def test_scorer_rejects_unrelated_quote(self):
        score = acceptance.score_case(
            self._case(), self._entry("import signal"))
        self.assertFalse(score["correct"])

    def test_scorer_accepts_distinct_relevant_quote(self):
        score = acceptance.score_case(
            self._case(), self._entry("RESULT = VALUE * 2"))
        self.assertTrue(score["correct"])


# ------------------------- FIX 2: region location -------------------------

# Two sibling call sites of the same construction, far apart:
# the FIRST (doctor path) already forwards the timeout; the
# SECOND (review path, the finding's cited line) does not —
# the P06 shape.
SIBLING_LINES = (
    ["# module header", "import os", "", "",
     "def build_doctor(args):",
     "    built = build_providers([pspec.strip()], "
     "agent_timeout=args.timeout)",
     "    return built",
     "", "", "", "", "", "", "", "", "", "", "", "", "",
     "", "", "", "", "", "", "", "", "", "", "", "", "",
     "def build_review(args):",
     "    built = build_providers([pspec.strip()])",
     "    return built"])
CITED_LINE = 35  # 1-based: the no-timeout construction
ANCHOR = "build_providers([pspec.strip()]"


class LocatePresentedRegionTests(unittest.TestCase):
    def test_cited_line_wins_over_first_anchor_hit(self):
        r = core.locate_presented_region(
            SIBLING_LINES, anchors=(ANCHOR,),
            cited_line=CITED_LINE, pad=2)
        self.assertTrue(r["located"])
        self.assertLessEqual(r["start_line"], CITED_LINE)
        self.assertGreaterEqual(r["end_line"], CITED_LINE)
        self.assertIn("build_providers([pspec.strip()])",
                      r["text"])
        self.assertNotIn("agent_timeout", r["text"])
        self.assertFalse(r["region_unverified"])

    def test_unplaceable_cited_line_marks_unverified(self):
        r = core.locate_presented_region(
            SIBLING_LINES, anchors=(ANCHOR,),
            cited_line=9999, pad=2)
        self.assertTrue(r["located"])  # the anchor region
        self.assertTrue(r["region_unverified"])
        self.assertIn("9999", r["note"])

    def test_no_cited_line_keeps_legacy_first_hit(self):
        r = core.locate_presented_region(
            SIBLING_LINES, anchors=(ANCHOR,), pad=2)
        self.assertTrue(r["located"])
        self.assertIn("agent_timeout", r["text"])
        self.assertFalse(r["region_unverified"])

    def test_anchor_window_containing_cited_line_is_anchor(self):
        r = core.locate_presented_region(
            SIBLING_LINES, anchors=(ANCHOR,),
            cited_line=6, pad=2)
        self.assertTrue(r["located"])
        self.assertEqual(r["located_via"], "anchor")
        self.assertFalse(r["region_unverified"])

    def test_no_anchor_hit_falls_back_to_cited_line(self):
        r = core.locate_presented_region(
            SIBLING_LINES, anchors=("no such text anywhere",),
            cited_line=CITED_LINE, pad=2)
        self.assertTrue(r["located"])
        self.assertEqual(r["located_via"], "cited_line")
        self.assertLessEqual(r["start_line"], CITED_LINE)
        self.assertGreaterEqual(r["end_line"], CITED_LINE)
        self.assertFalse(r["region_unverified"])


def _acceptance_case(line, start, end, **region_over):
    region = {"commit": "abc", "path": "src/x.py",
              "located": True, "start_line": start,
              "end_line": end, "text": "region text"}
    region.update(region_over)
    return {"case_id": "RX", "case_class": "synthetic",
            "title": "RX",
            "finding": {"claim": "some claim",
                        "evidence": "some evidence",
                        "evidence_quote": "q",
                        "severity_as_raised": "major",
                        "file": "src/x.py", "line": line,
                        "raised_by_family": "famA"},
            "refutation": {"by_family": "famB", "quote": "rq",
                           "reason": "wrong"},
            "code_region": region,
            "probe": None,
            "expected": {"decision": "escalate",
                         "severity_after": None,
                         "scoring": "exact"}}


class RegionUnverifiedInputTests(unittest.TestCase):
    def test_mislocated_region_marks_the_input(self):
        # The P06 shape at input-build time: cited line 951,
        # presented region 609-625.
        finding, _d, _r, _i = acceptance.case_inputs(
            _acceptance_case(951, 609, 625), "famC")
        self.assertTrue(finding.get("region_unverified"))

    def test_well_located_region_is_not_marked(self):
        finding, _d, _r, _i = acceptance.case_inputs(
            _acceptance_case(79, 75, 91), "famC")
        self.assertNotIn("region_unverified", finding)

    def test_builder_flag_propagates(self):
        finding, _d, _r, _i = acceptance.case_inputs(
            _acceptance_case(79, 75, 91,
                             region_unverified=True), "famC")
        self.assertTrue(finding.get("region_unverified"))

    def test_flag_is_loud_in_the_produced_record(self):
        finding = dict(FINDING, region_unverified=True)
        seat = _Seat([_payload(decision="escalate")])
        e = core.shadow_adjudicate(
            seat, finding, REGION, dict(DISPUTE),
            seat_name="tl", seat_family="famC")
        self.assertTrue(e.get("region_unverified"))


if __name__ == "__main__":
    unittest.main()
