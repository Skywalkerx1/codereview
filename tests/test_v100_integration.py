"""v0.10.0 — integration of the step4-ladder branch plus the
refutation-process solution's build steps 1–2 (owner-adopted
2026-11-04), and the step4 amendment review's two confirmed
majors:

- 1321bec43a24: no timeout guard on the Tech Lead call — each
  adjudication call now runs under a hard wait bound (the
  panel timeout wired through run_review's tech_lead_timeout).
- f6064fc5e515: the probe loop's one-round bound is an explicit
  counter (MAX_PROBE_ROUNDS), enforced and recorded, not an
  accident of the code's shape.
- Archived-record exclusion (solution §5.4): committed
  review-*/ output and gate-attempts.* ledgers never enter the
  reviewed span; findings citing archived-only text classify
  as archived-text and never reach adjudication.
- Evidence sidecars (solution §4 Q7): quotes, reasons and
  probe outputs are stored FULL-TEXT as content-addressed
  sidecars (evidence/<sha256>); the JSON keeps a display copy
  with a truncated flag; record-verify checks the hashes, and
  a tampered sidecar fails verification. Legacy (pre-sidecar)
  records verify as not-applicable.

All providers are scripted fakes; the git fixtures are real
temporary repositories, in the established suite style."""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

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
OTHER_LINE = "print(VALUE)"
THIRD_LINE = "RESULT = VALUE * 2"

META3 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"},
         "seatC": {"family": "famC", "tier": "paid"}}


def mk_finding(quote=CITED, sev="major", title="Total computed "
                                              "without a guard",
               evidence=None, file="app.py"):
    return {"severity": sev, "category": "correctness",
            "file": file, "line": 2, "title": title,
            "evidence": quote if evidence is None else evidence,
            "evidence_quote": quote,
            "recommendation": "guard it", "confidence": 0.9}


class Seat:
    """Scripted provider (same contract as test_step4_ladder's):
    answers per prompt kind; the tech_lead payload may be a LIST
    consumed in call order. `tl_delay` makes the adjudication
    answer arrive late (the timeout-guard tests)."""

    def __init__(self, review=None, xconfirm=None, tech_lead=None,
                 tl_delay=0.0):
        self.review = {"verdict": "pass", "summary": "ok",
                       "findings": []} if review is None else review
        self.xconfirm = {"verdict": "confirm"} \
            if xconfirm is None else xconfirm
        self.tech_lead = {
            "decision": "sustain_refutation",
            "evidence_quote": THIRD_LINE,
            "rationale": "the refutation is correct on the code"} \
            if tech_lead is None else tech_lead
        self.tl_delay = tl_delay

    def __call__(self, prompt):
        if "TECH LEAD ADJUDICATION pass" in prompt:
            if self.tl_delay:
                time.sleep(self.tl_delay)
            payload = self.tech_lead
            if isinstance(payload, list):
                payload = payload.pop(0) if len(payload) > 1 \
                    else payload[0]
        elif "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        elif "RE-GROUND pass" in prompt:
            payload = {"status": "withdrawn",
                       "reason": "cannot support it"}
        else:
            payload = self.review
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


def review3(a, b, c, **kw):
    kw.setdefault("seat_meta", META3)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(
        PATCH, {"seatA": a, "seatB": b, "seatC": c}, **kw)


def raiser(**kw):
    return Seat(review={"verdict": "changes_requested",
                        "findings": [mk_finding(**kw)]})


def refuter(quote=OTHER_LINE):
    return Seat(xconfirm={"verdict": "refute",
                          "evidence_quote": quote,
                          "reason": "the claim is wrong"})


class TechLeadTimeoutTests(unittest.TestCase):
    """Confirmed major 1321bec43a24: the adjudication call had
    no timeout guard — a hanging seat blocked the pipeline."""

    def test_bounded_job_returns_result_within_bound(self):
        res = core._review_job_bounded(
            lambda _p: '{"verdict": "pass"}', "prompt",
            max_attempts=1, timeout=5)
        self.assertTrue(res["ok"])

    def test_bounded_job_times_out_without_blocking(self):
        def hang(_p):
            time.sleep(3)
            return '{"verdict": "pass"}'
        start = time.monotonic()
        res = core._review_job_bounded(hang, "prompt",
                                       max_attempts=1, timeout=0.25)
        elapsed = time.monotonic() - start
        self.assertFalse(res["ok"])
        self.assertIn("timed out", str(res["error"]))
        self.assertLess(elapsed, 2.0)

    def test_bounded_job_rejects_nonpositive_timeout(self):
        res = core._review_job_bounded(
            lambda _p: "{}", "prompt", timeout=0)
        self.assertFalse(res["ok"])
        self.assertIn("must be positive", str(res["error"]))

    def test_hanging_tech_lead_escalates_instead_of_blocking(self):
        slow = Seat(tl_delay=3.0)
        start = time.monotonic()
        rec = review3(raiser(), refuter(), slow,
                      tech_lead_timeout=0.25)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2.5)
        self.assertEqual(len(rec["escalated_findings"]), 1)
        f = rec["escalated_findings"][0]
        adj = f["adjudication"]
        self.assertEqual(adj["raw_outcome"], "invalid")
        self.assertIn("timed out", adj["escalation_reason"])
        self.assertEqual(adj["call_timeout"], 0.25)
        self.assertEqual(rec["gate"], "inconclusive")

    def test_answering_tech_lead_unaffected_by_bound(self):
        rec = review3(raiser(), refuter(), Seat(),
                      tech_lead_timeout=5)
        self.assertEqual(len(rec["adjudicated_refuted_findings"]), 1)
        adj = rec["adjudicated_refuted_findings"][0]["adjudication"]
        self.assertEqual(adj["call_timeout"], 5)
        self.assertEqual(adj["probe_rounds"], 0)


class ProbeLoopBoundTests(unittest.TestCase):
    """Confirmed major f6064fc5e515: the one-round probe bound
    must be explicit and enforced — a Tech Lead that always
    answers needs_probe gets exactly MAX_PROBE_ROUNDS probes."""

    def test_bound_is_an_explicit_constant(self):
        self.assertEqual(core.MAX_PROBE_ROUNDS, 1)

    def test_repeated_needs_probe_escalates_after_one_round(self):
        calls = []

        def probe_fn(finding, request):
            calls.append(request)
            return {"outcome": "inconclusive",
                    "evidence_quote": "",
                    "detail": "probe could not settle it"}

        always = Seat(tech_lead=[
            {"decision": "needs_probe",
             "probe_request": "run the thing",
             "rationale": "cannot tell"},
            {"decision": "needs_probe",
             "probe_request": "run it again",
             "rationale": "still cannot tell"},
            {"decision": "needs_probe",
             "probe_request": "and again",
             "rationale": "never settles"}])
        rec = review3(raiser(), refuter(), always, probe_fn=probe_fn)
        self.assertEqual(len(calls), core.MAX_PROBE_ROUNDS)
        self.assertEqual(len(rec["escalated_findings"]), 1)
        adj = rec["escalated_findings"][0]["adjudication"]
        self.assertEqual(adj["probe_rounds"], core.MAX_PROBE_ROUNDS)
        self.assertIn("bounded", adj["rationale"])

    def test_single_probe_round_still_decides(self):
        calls = []

        def probe_fn(finding, request):
            calls.append(request)
            return {"outcome": "rebutted",
                    "evidence_quote": THIRD_LINE,
                    "detail": "the probe shows the guard exists"}

        tl = Seat(tech_lead=[
            {"decision": "needs_probe",
             "probe_request": "check for the guard",
             "rationale": "cannot tell from the region"},
            {"decision": "sustain_refutation",
             "evidence_quote": THIRD_LINE,
             "rationale": "the probe settles it"}])
        rec = review3(raiser(), refuter(), tl, probe_fn=probe_fn)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(rec["adjudicated_refuted_findings"]), 1)
        adj = rec["adjudicated_refuted_findings"][0]["adjudication"]
        self.assertEqual(adj["probe_rounds"], 1)
        self.assertEqual(adj["probe"]["outcome"], "rebutted")


if __name__ == "__main__":
    unittest.main()
