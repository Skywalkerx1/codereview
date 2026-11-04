"""Step 4 machinery (v15-closing-run solution §5, owner-adopted
2026-11-04): refutation-adequacy routing (§5a.1), third-family
tiebreak (§5a.3), the severity rubric + supported-platform
manifest as prompt/policy (§5b/§5c), deterministic platform-scope
labelling (§5c), and function-level precedent (§5d).

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
    tiebreak pass. A payload may be a dict, a raw string, or an
    Exception."""

    def __init__(self, review=None, reground=None, xconfirm=None,
                 tiebreak=None):
        self.review = {"verdict": "pass", "summary": "ok",
                       "findings": []} if review is None else review
        self.reground = {"status": "withdrawn",
                         "reason": "cannot support it"} \
            if reground is None else reground
        self.xconfirm = {"verdict": "confirm"} \
            if xconfirm is None else xconfirm
        self.tiebreak = {"verdict": "refute",
                         "evidence_quote": THIRD_LINE,
                         "reason": "the claim does not hold"} \
            if tiebreak is None else tiebreak

    def __call__(self, prompt):
        if "RE-GROUND pass" in prompt:
            payload = self.reground
        elif "THIRD-FAMILY TIEBREAK pass" in prompt:
            payload = self.tiebreak
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


class TiebreakTests(unittest.TestCase):
    def test_weak_plus_tiebreak_refute_resolves_and_passes(self):
        c = Seat(tiebreak={"verdict": "refute",
                           "evidence_quote": THIRD_LINE,
                           "reason": "no reachable defect"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(rec["findings"], [])
        self.assertNotIn("refutation_weak_findings", rec)
        res = rec["tiebreak_resolved_findings"]
        self.assertEqual(len(res), 1)
        f = res[0]
        self.assertEqual(f["status"], "tiebreak_refuted")
        self.assertEqual(f["tiebreak"]["seat"], "seatC")
        self.assertEqual(f["tiebreak"]["family"], "famC")
        self.assertEqual(f["tiebreak"]["outcome"], "refuted")
        self.assertEqual(f["tiebreak"]["evidence_quote"],
                         THIRD_LINE)
        self.assertEqual(f["dispute"]["evidence_quote"], CITED)

    def test_tiebreak_confirm_returns_finding_to_blocking(self):
        c = Seat(tiebreak={"verdict": "confirm",
                           "evidence_quote": THIRD_LINE,
                           "reason": "the defect is real"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(len(rec["findings"]), 1)
        f = rec["findings"][0]
        self.assertEqual(f["cross_family"], "tiebreak_confirmed")
        self.assertEqual(f["tiebreak"]["outcome"], "confirmed")
        self.assertNotIn("tiebreak_resolved_findings", rec)

    def test_strong_dispute_plus_tiebreak_confirm_blocks(self):
        c = Seat(tiebreak={"verdict": "confirm",
                           "evidence_quote": THIRD_LINE,
                           "reason": "raiser and I agree"})
        rec = review3(raiser(), refuter(OTHER_LINE), c)
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(rec["findings"][0]["cross_family"],
                         "tiebreak_confirmed")
        self.assertNotIn("disputed_findings", rec)

    def test_strong_dispute_plus_tiebreak_refute_resolves(self):
        rec = review3(raiser(), refuter(OTHER_LINE), Seat())
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(
            len(rec["tiebreak_resolved_findings"]), 1)
        self.assertNotIn("disputed_findings", rec)

    def test_tiebreak_vote_without_valid_quote_resolves_nothing(self):
        c = Seat(tiebreak={"verdict": "refute",
                           "evidence_quote": BOGUS_QUOTE,
                           "reason": "trust me"})
        rec = review3(raiser(), refuter(CITED), c)
        self.assertEqual(rec["gate"], "inconclusive")
        weak = rec["refutation_weak_findings"]
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["tiebreak"]["outcome"],
                         "unresolved")
        self.assertNotIn("tiebreak_resolved_findings", rec)

    def test_no_third_family_leaves_weak_state(self):
        # Two-seat panel: no family remains for a tiebreak.
        rec = review2(raiser(), refuter(CITED))
        weak = rec["refutation_weak_findings"]
        self.assertEqual(len(weak), 1)
        self.assertNotIn("tiebreak", weak[0])


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

    def test_tiebreak_prompt_demands_quotes(self):
        self.assertIn("THIRD-FAMILY TIEBREAK pass",
                      core._TIEBREAK_PROMPT)
        self.assertIn("evidence_quote", core._TIEBREAK_PROMPT)


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
