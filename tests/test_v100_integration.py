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


ARCHIVED_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "diff --git a/review-v096/codereview-20261104-000000.json "
    "b/review-v096/codereview-20261104-000000.json\n"
    "--- /dev/null\n"
    "+++ b/review-v096/codereview-20261104-000000.json\n"
    "@@ -0,0 +1,2 @@\n"
    "+{\"findings\": [{\"evidence\": \"result = "
    "eval(preserved_input)\"}]}\n"
    "+{\"note\": \"pre-fix lines preserved as evidence\"}\n"
    "diff --git a/gate-attempts.jsonl b/gate-attempts.jsonl\n"
    "--- /dev/null\n"
    "+++ b/gate-attempts.jsonl\n"
    "@@ -0,0 +1,1 @@\n"
    "+{\"gate\": \"blocked\", \"range\": \"a..b\"}\n")


class RecordingSeat:
    """Pass-verdict seat that remembers every prompt it saw."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})


class ArchivedExclusionFlowTests(unittest.TestCase):
    """Solution §5.4: committed review records and the attempts
    ledger are excluded from the span, visibly, and findings
    citing them classify as archived-text."""

    def run_archived(self):
        seats = [RecordingSeat(), RecordingSeat(), RecordingSeat()]
        rec = core.run_review(
            ARCHIVED_PATCH,
            {"seatA": seats[0], "seatB": seats[1],
             "seatC": seats[2]},
            seat_meta=META3, sleep=lambda *_a: None)
        return rec, seats

    def test_exclusions_listed_with_rules(self):
        rec, _seats = self.run_archived()
        self.assertEqual(
            rec["archived_exclusions"],
            [{"path": "review-v096/codereview-20261104-000000.json",
              "rule": "review-*/"},
             {"path": "gate-attempts.jsonl",
              "rule": "gate-attempts.*"}])
        self.assertEqual(rec["files"], ["app.py"])
        self.assertEqual(
            set(rec["coverage"]["files"]), {"app.py"})
        self.assertTrue(any("archived-record rule" in r
                            for r in rec["gate_reasons"]))

    def test_reviewers_never_see_archived_sections(self):
        _rec, seats = self.run_archived()
        seen = "\n".join(p for s in seats for p in s.prompts)
        self.assertNotIn("preserved_input", seen)
        self.assertIn("compute_total", seen)

    def test_det_finding_on_archived_path_classified(self):
        rec, _seats = self.run_archived()
        # The preserved eval( line would be a deterministic
        # BLOCKER as live code; as archived text it is preserved
        # in archived_text_findings and cannot block the gate.
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(
            [f for f in rec["findings"]
             if f.get("rule") == "eval-exec"], [])
        arch = rec["archived_text_findings"]
        self.assertEqual(len(arch), 1)
        self.assertEqual(arch[0]["rule"], "eval-exec")
        self.assertEqual(arch[0]["archived_text"],
                         {"rule": "review-*/", "basis": "path"})

    def test_span_without_archives_records_no_exclusions(self):
        rec = review3(Seat(), Seat(), Seat())
        self.assertNotIn("archived_exclusions", rec)
        self.assertNotIn("archived_text_findings", rec)


class ArchivedTextClassifierTests(unittest.TestCase):
    """Unit coverage of _split_archived_text's two bases."""

    ARCH = [("review-v15/rec.json",
             "header\nOLD PREFIX LINE preserved\nfooter\n")]
    KEPT_FILES = {"app.py"}
    KEPT_TEXT = "VALUE = compute_total(items)\n"

    def classify(self, findings):
        return core._split_archived_text(
            findings, self.KEPT_FILES, self.KEPT_TEXT, self.ARCH)

    def test_path_basis(self):
        f = {"file": "gate-attempts.jsonl", "evidence_quote": "x"}
        kept, arch = self.classify([f])
        self.assertEqual(kept, [])
        self.assertEqual(arch[0]["archived_text"],
                         {"rule": "gate-attempts.*",
                          "basis": "path"})

    def test_quote_basis_reraise_shape(self):
        # The v0.9.6 re-raise shape: a claim about a source file
        # whose cited text exists ONLY inside a committed record.
        f = {"file": "src/codereview/core.py",
             "evidence_quote": "OLD PREFIX LINE preserved"}
        kept, arch = self.classify([f])
        self.assertEqual(kept, [])
        self.assertEqual(arch[0]["archived_text"],
                         {"rule": "archived-text",
                          "basis": "quote"})

    def test_quote_also_in_reviewed_material_stays(self):
        f = {"file": "src/codereview/core.py",
             "evidence_quote": "VALUE = compute_total(items)"}
        kept, arch = self.classify([f])
        self.assertEqual(arch, [])
        self.assertEqual(kept, [f])

    def test_no_archived_sections_passthrough(self):
        f = {"file": "review-v15/rec.json", "evidence_quote": "x"}
        kept, arch = core._split_archived_text(
            [f], self.KEPT_FILES, self.KEPT_TEXT, [])
        self.assertEqual((kept, arch), ([f], []))


LONG_LINE = "VALUE = compute_total(" + ", ".join(
    f"item_{i}" for i in range(80)) + ")"
LONG_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " import os\n"
    f"+{LONG_LINE}\n")


def _check(result, name):
    for c in result["checks"]:
        if c["name"] == name:
            return c
    raise AssertionError(f"check {name} not present")


class EvidenceSidecarTests(unittest.TestCase):
    """Solution §4 Q7: full-text, hash-verified evidence."""

    def write(self, report):
        tmp = tempfile.mkdtemp()
        jpath, _mpath = core.write_report(report, tmp)
        with open(jpath, encoding="utf-8") as fh:
            return tmp, json.load(fh)

    def test_long_quote_round_trips_in_full_via_sidecar(self):
        self.assertGreater(len(LONG_LINE), 400)
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(
                             quote=LONG_LINE, sev="minor")]})
        rec = core.run_review(
            LONG_PATCH, {"seatA": a, "seatB": Seat()},
            seat_meta={"seatA": {"family": "famA", "tier": "paid"},
                       "seatB": {"family": "famB", "tier": "paid"}},
            sleep=lambda *_a: None)
        _tmp, written = self.write(rec)
        f = written["findings"][0]
        ref = f["evidence_quote_ref"]
        self.assertTrue(ref["truncated"])
        self.assertEqual(ref["length"], len(LONG_LINE))
        self.assertEqual(f["evidence_quote"], LONG_LINE[:400])
        sidecar = os.path.join(_tmp, "evidence", ref["sha256"])
        with open(sidecar, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), LONG_LINE)
        self.assertEqual(
            ref["sha256"],
            hashlib.sha256(LONG_LINE.encode()).hexdigest())
        self.assertEqual(written["evidence_sidecars"]["dir"],
                         "evidence")

    def test_short_quote_ref_not_truncated(self):
        rec = review3(raiser(), Seat(), Seat())
        _tmp, written = self.write(rec)
        f = written["findings"][0]
        ref = f["evidence_quote_ref"]
        self.assertFalse(ref["truncated"])
        self.assertEqual(f["evidence_quote"], CITED)

    def test_caller_report_is_not_mutated(self):
        rec = review3(raiser(), Seat(), Seat())
        self.write(rec)
        self.assertNotIn("evidence_quote_ref", rec["findings"][0])
        self.assertNotIn("evidence_sidecars", rec)

    def test_dispute_texts_full_and_evidence_complete(self):
        long_reason = "the claim fails because " + "x" * 400
        b = Seat(xconfirm={"verdict": "refute",
                           "evidence_quote": OTHER_LINE,
                           "reason": long_reason})
        long_detail = "probe output " + "y" * 700
        tl = Seat(tech_lead=[
            {"decision": "needs_probe",
             "probe_request": "check the guard",
             "rationale": "cannot tell"},
            {"decision": "sustain_refutation",
             "evidence_quote": THIRD_LINE,
             "rationale": "settled " + "z" * 700}])
        rec = review3(raiser(), b, tl, probe_fn=lambda _f, _r: {
            "outcome": "rebutted", "evidence_quote": THIRD_LINE,
            "detail": long_detail})
        _tmp, written = self.write(rec)
        f = written["adjudicated_refuted_findings"][0]
        self.assertTrue(f["evidence_complete"])
        d_ref = f["dispute"]["reason_ref"]
        self.assertEqual(d_ref["length"], len(long_reason))
        self.assertTrue(d_ref["truncated"])
        self.assertEqual(f["dispute"]["reason"],
                         long_reason[:300])
        adj = f["adjudication"]
        self.assertEqual(adj["rationale_ref"]["length"],
                         len("settled " + "z" * 700))
        self.assertEqual(adj["probe"]["detail_ref"]["length"],
                         len(long_detail))
        # ...and the record verifies against its own sidecars.
        result = core.verify_record(written, repo=_tmp,
                                    record_dir=".")
        check = _check(result, "evidence_sidecars")
        self.assertTrue(check["ok"], check["detail"])

    def test_tampered_sidecar_fails_verification(self):
        rec = review3(raiser(), Seat(), Seat())
        tmp, written = self.write(rec)
        ref = written["findings"][0]["evidence_quote_ref"]
        path = os.path.join(tmp, "evidence", ref["sha256"])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("tampered evidence")
        result = core.verify_record(written, repo=tmp,
                                    record_dir=".")
        check = _check(result, "evidence_sidecars")
        self.assertFalse(check["ok"])
        self.assertIn("does not hash", check["detail"])

    def test_missing_sidecar_fails_verification(self):
        rec = review3(raiser(), Seat(), Seat())
        tmp, written = self.write(rec)
        ref = written["findings"][0]["evidence_quote_ref"]
        os.unlink(os.path.join(tmp, "evidence", ref["sha256"]))
        result = core.verify_record(written, repo=tmp,
                                    record_dir=".")
        self.assertFalse(
            _check(result, "evidence_sidecars")["ok"])

    def test_legacy_record_sidecar_check_not_applicable(self):
        # A real pre-sidecar record (review-v096, written by
        # v0.9.6): no refs anywhere -> the check passes as
        # not-applicable and nothing else about the record's
        # verification changes. Read from the fixture copy under
        # tests/fixtures/historical-records/ (D-003: the sdist
        # ships tests/fixtures, not the repo-root run-output
        # dirs; the original stays untouched).
        repo = os.path.join(os.path.dirname(__file__), "fixtures",
                            "historical-records")
        rdir = os.path.join(repo, "review-v096")
        names = [n for n in os.listdir(rdir) if n.endswith(".json")]
        self.assertTrue(names)
        with open(os.path.join(rdir, names[0]),
                  encoding="utf-8") as fh:
            legacy = json.load(fh)
        self.assertEqual(list(core._iter_evidence_refs(legacy)),
                         [])
        result = core.verify_record(legacy, repo=repo,
                                    record_dir="review-v096")
        check = _check(result, "evidence_sidecars")
        self.assertTrue(check["ok"])
        self.assertIn("not applicable", check["detail"])


if __name__ == "__main__":
    unittest.main()
