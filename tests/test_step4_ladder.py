"""Step 4 machinery (v15-closing-run solution §5, owner-adopted
2026-11-04): refutation-adequacy routing (§5a.1), Tech Lead
adjudication (owner amendment 2026-11-04, superseding the
§5a.3 tiebreak: an independent third role decides finally —
sustain_finding / sustain_refutation / needs-probe / escalate —
with loud substitution of an ineligible designated seat), the
severity rubric + supported-platform manifest as prompt/policy
(§5b/§5c), deterministic platform-scope labelling (§5c), and
function-level precedent (§5d).

All providers are scripted fakes; the git fixtures are real
temporary repositories, in the established suite style."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
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
BOGUS_QUOTE = "a line that appears nowhere in this diff"

META2 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"}}
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
    """Scripted provider: answers per prompt kind, including the
    Tech Lead adjudication pass. A payload may be a dict, a raw
    string, or an Exception; the tech_lead payload may be a LIST
    of payloads consumed in call order (the needs-probe loop
    calls the Tech Lead twice)."""

    def __init__(self, review=None, reground=None, xconfirm=None,
                 tech_lead=None):
        self.review = {"verdict": "pass", "summary": "ok",
                       "findings": []} if review is None else review
        self.reground = {"status": "withdrawn",
                         "reason": "cannot support it"} \
            if reground is None else reground
        self.xconfirm = {"verdict": "confirm"} \
            if xconfirm is None else xconfirm
        self.tech_lead = {
            "decision": "sustain_refutation",
            "evidence_quote": THIRD_LINE,
            "rationale": "the refutation is correct on the code"} \
            if tech_lead is None else tech_lead

    def __call__(self, prompt):
        if "RE-GROUND pass" in prompt:
            payload = self.reground
        elif "TECH LEAD ADJUDICATION pass" in prompt:
            payload = self.tech_lead
            if isinstance(payload, list):
                payload = payload.pop(0) if len(payload) > 1 \
                    else payload[0]
        elif "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        else:
            payload = self.review
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


def review2(a, b, **kw):
    kw.setdefault("seat_meta", META2)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(PATCH, {"seatA": a, "seatB": b}, **kw)


def review3(a, b, c, **kw):
    kw.setdefault("seat_meta", META3)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(
        PATCH, {"seatA": a, "seatB": b, "seatC": c}, **kw)


def raiser(**kw):
    return Seat(review={"verdict": "changes_requested",
                        "findings": [mk_finding(**kw)]})


def refuter(quote):
    return Seat(xconfirm={"verdict": "refute",
                          "evidence_quote": quote,
                          "reason": "the claim is wrong"})


class AdequacyUnitTests(unittest.TestCase):
    def test_same_quote_is_weak(self):
        self.assertTrue(core._refutation_weak(
            {"evidence_quote": CITED}, CITED))

    def test_plus_marker_and_whitespace_tolerated(self):
        self.assertTrue(core._refutation_weak(
            {"evidence_quote": CITED}, "  +" + CITED + " "))

    def test_different_line_is_strong(self):
        self.assertFalse(core._refutation_weak(
            {"evidence_quote": CITED}, OTHER_LINE))

    def test_no_cited_quote_is_not_weak(self):
        self.assertFalse(core._refutation_weak({}, CITED))
        self.assertFalse(core._refutation_weak(
            {"evidence_quote": ""}, ""))


class AdequacyFlowTests(unittest.TestCase):
    def test_weak_refutation_routes_to_weak_list(self):
        rec = review2(raiser(), refuter(CITED))
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertEqual(rec["findings"], [])
        self.assertNotIn("disputed_findings", rec)
        weak = rec["refutation_weak_findings"]
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["status"], "refutation_weak")
        self.assertEqual(weak[0]["cross_family"], "refuted_weak")
        self.assertEqual(weak[0]["dispute"]["adequacy"], "weak")
        self.assertEqual(weak[0]["dispute"]["by"], "seatB")

    def test_strong_refutation_stays_disputed(self):
        rec = review2(raiser(), refuter(OTHER_LINE))
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertNotIn("refutation_weak_findings", rec)
        d = rec["disputed_findings"][0]
        self.assertEqual(d["status"], "disputed")
        self.assertEqual(d["dispute"]["adequacy"], "strong")


PRECEDENTS_CTX = {"entries": [],
                  "blob_lookup": lambda p: "BLOB1",
                  "source_lookup": lambda p: None}


class TechLeadTests(unittest.TestCase):
    def test_weak_refutation_sustained_by_tech_lead(self):
        rec = review3(raiser(), refuter(CITED), Seat())
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(rec["findings"], [])
        self.assertNotIn("refutation_weak_findings", rec)
        self.assertNotIn("disputed_findings", rec)
        adj_list = rec["adjudicated_refuted_findings"]
        self.assertEqual(len(adj_list), 1)
        f = adj_list[0]
        self.assertEqual(f["status"], "adjudicated_refuted")
        self.assertEqual(f["cross_family"], "tech_lead_refuted")
        adj = f["adjudication"]
        self.assertEqual(adj["role"], "tech_lead")
        self.assertEqual(adj["seat"], "seatC")
        self.assertEqual(adj["family"], "famC")
        self.assertEqual(adj["tier"], "paid")
        self.assertEqual(adj["decision"], "sustain_refutation")
        self.assertEqual(adj["evidence_quote"], THIRD_LINE)
        self.assertEqual(adj["positions"]["refuter"]["adequacy"],
                         "weak")
        self.assertEqual(adj["positions"]["raiser"]["family"],
                         "famA")
        self.assertEqual(f["precedent_eligible"],
                         "sustain_refutation")

    def test_strong_dispute_also_adjudicated(self):
        rec = review3(raiser(), refuter(OTHER_LINE), Seat())
        self.assertEqual(rec["gate"], "pass")
        self.assertNotIn("disputed_findings", rec)
        f = rec["adjudicated_refuted_findings"][0]
        self.assertEqual(
            f["adjudication"]["positions"]["refuter"]["adequacy"],
            "strong")

    def test_sustain_finding_returns_to_blocking(self):
        c = Seat(tech_lead={"decision": "sustain_finding",
                            "evidence_quote": THIRD_LINE,
                            "rationale": "the defect is real"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(len(rec["findings"]), 1)
        f = rec["findings"][0]
        self.assertEqual(f["cross_family"], "tech_lead_sustained")
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["adjudication"]["decision"],
                         "sustain_finding")
        self.assertNotIn("adjudicated_refuted_findings", rec)

    def test_downgrade_applies_loudly_and_is_precedent_eligible(self):
        c = Seat(tech_lead={"decision": "sustain_finding",
                            "severity": "minor",
                            "evidence_quote": THIRD_LINE,
                            "rationale": "real but not reachable "
                                         "as a major"})
        rec = review3(raiser(), refuter(OTHER_LINE), c,
                      precedents=PRECEDENTS_CTX)
        self.assertEqual(rec["gate"], "pass")
        f = rec["findings"][0]
        self.assertEqual(f["severity"], "minor")
        self.assertEqual(f["severity_before_adjudication"],
                         "major")
        adj = f["adjudication"]
        self.assertEqual(adj["severity_before"], "major")
        self.assertEqual(adj["severity_applied"], "minor")
        self.assertEqual(f["precedent_eligible"],
                         "rubric_downgrade")
        cands = rec["precedent_candidates"]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["finding_id"], f["id"])
        self.assertEqual(cands[0]["blob"], "BLOB1")

    def test_severity_upgrade_never_applied(self):
        c = Seat(tech_lead={"decision": "sustain_finding",
                            "severity": "blocker",
                            "evidence_quote": THIRD_LINE,
                            "rationale": "worse than claimed"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "blocked")
        f = rec["findings"][0]
        self.assertEqual(f["severity"], "major")
        self.assertEqual(f["adjudication"]["severity_requested"],
                         "blocker")
        self.assertIn("never raise",
                      f["adjudication"]["severity_note"])

    def test_sustain_refutation_records_precedent_candidate(self):
        rec = review3(raiser(), refuter(CITED), Seat(),
                      precedents=PRECEDENTS_CTX)
        cands = rec["precedent_candidates"]
        self.assertEqual(len(cands), 1)
        f = rec["adjudicated_refuted_findings"][0]
        self.assertEqual(cands[0]["finding_id"], f["id"])
        self.assertEqual(cands[0]["path"], "app.py")
        self.assertEqual(cands[0]["blob"], "BLOB1")

    def test_needs_probe_loop_decides_on_combined_evidence(self):
        calls = []

        def probe(finding, request):
            calls.append(request)
            return {"outcome": "rebutted",
                    "evidence_quote": THIRD_LINE,
                    "detail": "probe: the call site guards the "
                              "total before use"}

        c = Seat(tech_lead=[
            {"decision": "needs_probe",
             "probe_request": "check whether the caller guards "
                              "the total",
             "rationale": "the region alone cannot settle it"},
            {"decision": "sustain_refutation",
             "evidence_quote": THIRD_LINE,
             "rationale": "the probe confirms the guard"}])
        rec = review3(raiser(), refuter(CITED), c, probe_fn=probe)
        self.assertEqual(len(calls), 1)
        self.assertIn("guards", calls[0])
        self.assertEqual(rec["gate"], "pass")
        f = rec["adjudicated_refuted_findings"][0]
        self.assertEqual(f["adjudication"]["probe"]["outcome"],
                         "rebutted")
        self.assertEqual(f["adjudication"]["decision"],
                         "sustain_refutation")

    def test_needs_probe_without_channel_escalates(self):
        c = Seat(tech_lead={"decision": "needs_probe",
                            "probe_request": "run the caller",
                            "rationale": "cannot settle it here"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "inconclusive")
        esc = rec["escalated_findings"]
        self.assertEqual(len(esc), 1)
        self.assertIn("probe",
                      esc[0]["adjudication"]["escalation_reason"])

    def test_escalate_on_degraded_panel(self):
        meta4 = dict(META3)
        meta4["seatD"] = {"family": "famD", "tier": "paid"}
        d = Seat(review=RuntimeError("seat down"))
        c = Seat(tech_lead={
            "decision": "escalate",
            "rationale": "the panel degraded and the remaining "
                         "evidence cannot carry a final decision"})
        rec = core.run_review(
            PATCH, {"seatA": raiser(), "seatB": refuter(CITED),
                    "seatC": c, "seatD": d},
            seat_meta=meta4, sleep=lambda *_a: None)
        self.assertTrue(rec["degraded"])
        self.assertEqual(rec["gate"], "inconclusive")
        esc = rec["escalated_findings"]
        self.assertEqual(len(esc), 1)
        self.assertEqual(esc[0]["status"], "escalated")
        self.assertIn("degraded",
                      esc[0]["adjudication"]["escalation_reason"])

    def test_unvalidated_decision_escalates_loudly(self):
        c = Seat(tech_lead={"decision": "sustain_refutation",
                            "evidence_quote": BOGUS_QUOTE,
                            "rationale": "trust me"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "inconclusive")
        esc = rec["escalated_findings"]
        self.assertEqual(len(esc), 1)
        adj = esc[0]["adjudication"]
        self.assertEqual(adj["decision"], "escalate")
        self.assertEqual(adj["raw_outcome"], "invalid")
        self.assertIn("no quote", adj["escalation_reason"])
        self.assertNotIn("adjudicated_refuted_findings", rec)

    def test_designated_refuter_family_substituted_loudly(self):
        rec = review3(raiser(), refuter(CITED), Seat(),
                      tech_lead="seatB")
        f = rec["adjudicated_refuted_findings"][0]
        self.assertEqual(f["adjudication"]["seat"], "seatC")
        sub = f["adjudication"]["substitution"]
        self.assertEqual(sub["designated"], "seatB")
        self.assertIn("independent", sub["reason"])
        subs = rec["tech_lead_substitutions"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["substitute"], "seatC")
        self.assertTrue(any("substitution" in r.lower()
                            for r in rec["gate_reasons"]))

    def test_designated_independent_seat_serves_without_substitution(self):
        rec = review3(raiser(), refuter(CITED), Seat(),
                      tech_lead="seatC")
        f = rec["adjudicated_refuted_findings"][0]
        self.assertEqual(f["adjudication"]["seat"], "seatC")
        self.assertNotIn("substitution", f["adjudication"])
        self.assertNotIn("tech_lead_substitutions", rec)

    def test_designated_same_family_without_substitute_stays_disputed(self):
        rec = review2(raiser(), refuter(OTHER_LINE),
                      tech_lead="seatB")
        self.assertEqual(rec["gate"], "inconclusive")
        d = rec["disputed_findings"][0]
        self.assertEqual(d["tech_lead"]["status"], "unavailable")
        self.assertEqual(
            d["tech_lead"]["substitution"]["designated"], "seatB")
        self.assertIn("independent",
                      d["tech_lead"]["substitution"]["reason"])

    def test_no_third_family_leaves_weak_state(self):
        # Two-seat panel: no family remains to adjudicate.
        rec = review2(raiser(), refuter(CITED))
        weak = rec["refutation_weak_findings"]
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["tech_lead"]["status"],
                         "unavailable")
        self.assertNotIn("adjudication", weak[0])


class PlatformScopeTests(unittest.TestCase):
    WIN_EVIDENCE = ("On Windows, ntpath.join raises when the "
                    "paths sit on different drives")
    WIN_TITLE = "Path join breaks across drive letters"

    def test_windows_only_finding_labelled_out_of_scope(self):
        rec = review2(
            raiser(title=self.WIN_TITLE, evidence=self.WIN_EVIDENCE),
            Seat())
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(rec["findings"], [])
        oos = rec["out_of_scope_findings"]
        self.assertEqual(len(oos), 1)
        self.assertEqual(oos[0]["platform_scope"],
                         "out-of-scope (documented)")
        self.assertIn("unsupported platform",
                      oos[0]["platform_reason"])

    def test_supported_platform_mention_blocks_labelling(self):
        ev = self.WIN_EVIDENCE + "; the same join also fails on POSIX"
        rec = review2(raiser(title=self.WIN_TITLE, evidence=ev),
                      Seat())
        self.assertEqual(rec["gate"], "blocked")
        self.assertNotIn("out_of_scope_findings", rec)
        self.assertEqual(len(rec["findings"]), 1)

    def test_plain_finding_not_labelled(self):
        self.assertIsNone(core._platform_scope(mk_finding()))

    def test_record_carries_supported_platforms(self):
        rec = review2(Seat(), Seat())
        self.assertEqual(rec["supported_platforms"],
                         {"os": ["posix"], "python": ">=3.11"})


class RubricPolicyTests(unittest.TestCase):
    def test_review_prompt_states_rubric_and_manifest(self):
        self.assertIn("reachable defect", core._REVIEW_PROMPT)
        self.assertIn(">= 3.11", core._REVIEW_PROMPT)
        self.assertIn("hypothetical future seat kinds",
                      core._REVIEW_PROMPT)

    def test_verify_prompt_states_rubric(self):
        self.assertIn("reachable defect", core._VERIFY_PROMPT)
        self.assertIn("hypothetical future seat kinds",
                      core._VERIFY_PROMPT)

    def test_tech_lead_prompt_names_role_and_decisions(self):
        self.assertIn("TECH LEAD ADJUDICATION pass",
                      core._TECH_LEAD_PROMPT)
        self.assertIn("Tech Lead", core._TECH_LEAD_PROMPT)
        for decision in ("sustain_finding", "sustain_refutation",
                         "needs_probe", "escalate"):
            self.assertIn(decision, core._TECH_LEAD_PROMPT)
        self.assertIn("no majority vote",
                      core._TECH_LEAD_PROMPT.lower())


SRC_V1 = (
    "def helper(x):\n"
    "    return x + 1\n"
    "\n"
    "\n"
    "def judged(items):\n"
    "    total = helper(items)\n"
    "    return total\n"
    "\n"
    "\n"
    "def other():\n"
    "    return 42\n")
SRC_UNRELATED_EDIT = SRC_V1.replace("return 42", "return 43")
SRC_FUNCTION_EDIT = SRC_V1.replace(
    "total = helper(items)", "total = helper(items) + 1")
SRC_CALLEE_EDIT = SRC_V1.replace("return x + 1", "return x + 2")
JUDGED_LINE = 6  # `total = helper(items)` inside judged()


def fn_finding(line=JUDGED_LINE):
    return {"id": "fnfid", "file": "mod.py", "line": line,
            "severity": "minor", "title": "t",
            "sources": ["seatA"], "consensus": False}


class FunctionKeyTests(unittest.TestCase):
    def test_key_shape(self):
        fk = core.function_key(SRC_V1, JUDGED_LINE)
        self.assertEqual(fk["function"], "judged")
        self.assertIn("helper", fk["callees"])
        self.assertEqual(len(fk["function_hash"]), 64)

    def test_unrelated_edit_keeps_key(self):
        self.assertEqual(core.function_key(SRC_V1, JUDGED_LINE),
                         core.function_key(SRC_UNRELATED_EDIT,
                                           JUDGED_LINE))

    def test_line_outside_any_function_unresolvable(self):
        self.assertIsNone(core.function_key(SRC_V1, 3))
        self.assertIsNone(core.function_key("def broken(:\n", 1))
        self.assertIsNone(core.function_key(SRC_V1, None))


class FunctionPrecedentTests(unittest.TestCase):
    def _entries(self):
        return core.upsert_precedent(
            [], fn_finding(), "B1", "r1", "d.md", "s",
            source=SRC_V1)

    def test_upsert_stamps_function_fields(self):
        e = self._entries()[0]
        self.assertEqual(e["function"], "judged")
        self.assertEqual(e["scope"], "function")
        self.assertIn("helper", e["callees"])
        self.assertEqual(e["blob"], "B1")

    def test_unrelated_edit_keeps_precedent_despite_blob_change(self):
        remaining, standing = core.apply_precedents(
            [fn_finding()], self._entries(), lambda p: "B2",
            source_lookup=lambda p: SRC_UNRELATED_EDIT)
        self.assertEqual(remaining, [])
        self.assertEqual(len(standing), 1)
        link = standing[0]["precedent"]
        self.assertEqual(link["scope"], "function")
        self.assertEqual(link["function"], "judged")

    def test_edit_inside_function_reopens(self):
        remaining, standing = core.apply_precedents(
            [fn_finding()], self._entries(), lambda p: "B2",
            source_lookup=lambda p: SRC_FUNCTION_EDIT)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(standing, [])

    def test_callee_edit_reopens(self):
        remaining, standing = core.apply_precedents(
            [fn_finding()], self._entries(), lambda p: "B2",
            source_lookup=lambda p: SRC_CALLEE_EDIT)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(standing, [])

    def test_unresolvable_function_falls_back_to_blob(self):
        remaining, standing = core.apply_precedents(
            [fn_finding(line=3)], self._entries(), lambda p: "B1",
            source_lookup=lambda p: SRC_V1)
        self.assertEqual(remaining, [])
        self.assertEqual(standing[0]["precedent"]["scope"], "file")
        remaining, standing = core.apply_precedents(
            [fn_finding(line=3)], self._entries(), lambda p: "B2",
            source_lookup=lambda p: SRC_V1)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(standing, [])

    def test_legacy_file_entry_still_works(self):
        entries = [{"finding_id": "fnfid", "path": "mod.py",
                    "blob": "B1", "seen_in": ["r1"],
                    "disposition": {"round": "r1", "file": "d.md",
                                    "summary": "s"}}]
        remaining, standing = core.apply_precedents(
            [fn_finding()], entries, lambda p: "B1",
            source_lookup=lambda p: SRC_V1)
        self.assertEqual(remaining, [])
        self.assertEqual(standing[0]["precedent"]["scope"], "file")


class _GitRepo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        env = dict(os.environ, HOME="/home/hatch")
        self.env = env

        def git(*args):
            return subprocess.run(
                ["git", "-C", self.td, "-c", "user.email=t@t",
                 "-c", "user.name=t", *args],
                capture_output=True, text=True, env=env,
                check=True).stdout.strip()

        self.git = git
        git("init", "-q")

    def write_commit(self, files, message):
        for path, content in files.items():
            full = os.path.join(self.td, path)
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")


class FunctionPrecedentVerifyTests(_GitRepo):
    def setUp(self):
        super().setUp()
        self.c1 = self.write_commit({"mod.py": SRC_V1}, "c1")
        blob = self.git("rev-parse", "HEAD:mod.py")
        entry = core.upsert_precedent(
            [], fn_finding(), blob, "r1", "d.md", "s",
            source=SRC_V1)[0]
        store = {"schema": core.PRECEDENTS_SCHEMA,
                 "entries": [entry]}
        self.store_bytes = json.dumps(store).encode("utf-8")
        self.c1 = self.write_commit(
            {"precedents.json": self.store_bytes.decode("utf-8")},
            "c1b")
        fk = core.function_key(SRC_V1, JUDGED_LINE)
        self.standing = [{
            "id": "fnfid", "file": "mod.py", "line": JUDGED_LINE,
            "severity": "minor", "title": "t",
            "sources": ["seatA"], "consensus": False,
            "standing": True,
            "precedent": {
                "scope": "function", "blob": blob,
                "function": fk["function"],
                "function_hash": fk["function_hash"],
                "callees": fk["callees"], "repeats": 1,
                "disposition": {"round": "r1", "file": "d.md",
                                "summary": "s"}}}]
        self.record = {
            "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "lens": "correctness",
                 "status": "ok", "family": "google"},
                {"provider": "n", "lens": "operations",
                 "status": "ok", "family": "nvidia"}],
            "standing_findings": self.standing,
            "precedent_scope": {
                "store_path": "precedents.json",
                "store_sha256": hashlib.sha256(
                    self.store_bytes).hexdigest(),
                "entries_applied": 1}}

    def _check(self, record):
        result = core.verify_record(record, repo=self.td,
                                    record_dir="r1")
        return {c["name"]: c for c in result["checks"]}[
            "precedent_scope_valid"]

    def _finish(self, files, message):
        head = self.write_commit(files, message)
        self.record["range"] = f"{self.c1}..{head}"
        self.record["head"] = head
        patch = core.collect_git_patch(
            self.td, range_spec=self.record["range"])
        self.record["patch_sha256"] = hashlib.sha256(
            patch.encode("utf-8")).hexdigest()

    def test_unrelated_edit_at_head_still_valid(self):
        self._finish({"mod.py": SRC_UNRELATED_EDIT}, "c2")
        check = self._check(self.record)
        self.assertTrue(check["ok"], check)

    def test_function_edit_at_head_fails(self):
        self._finish({"mod.py": SRC_FUNCTION_EDIT}, "c2")
        self.assertFalse(self._check(self.record)["ok"])

    def test_callee_edit_at_head_fails(self):
        self._finish({"mod.py": SRC_CALLEE_EDIT}, "c2")
        self.assertFalse(self._check(self.record)["ok"])


if __name__ == "__main__":
    unittest.main()
