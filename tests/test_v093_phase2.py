"""v0.9.3 Phase 2 machinery (v14-hold solution §2, owner-adopted):
coverage accounting (§2a), evidence grounding + re-ground (§2b),
cross-family confirmation (§2c), Form B chain verification
(§2d), record-and-attest tier policy (§2, decision (a)), and
content-addressed precedent (§2e, decision (b)).

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
    "@@ -1,1 +1,3 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n")
GOOD_QUOTE = "VALUE = compute_total(items)"
BOGUS_QUOTE = "a line that appears nowhere in this diff"

META = {"seatA": {"family": "famA", "tier": "paid"},
        "seatB": {"family": "famB", "tier": "free"}}


def mk_finding(quote, sev="major", title="Total computed without "
                                         "a guard", file="app.py"):
    return {"severity": sev, "category": "correctness",
            "file": file, "line": 2, "title": title,
            "evidence": quote, "evidence_quote": quote,
            "recommendation": "guard it", "confidence": 0.9}


class Seat:
    """Scripted provider: answers per prompt kind. A payload may
    be a dict (JSON-encoded), a raw string, or an Exception."""

    def __init__(self, review=None, reground=None, xconfirm=None):
        self.review = {"verdict": "pass", "summary": "ok",
                       "findings": []} if review is None else review
        self.reground = {"status": "withdrawn",
                         "reason": "cannot support it"} \
            if reground is None else reground
        self.xconfirm = {"verdict": "confirm"} \
            if xconfirm is None else xconfirm

    def __call__(self, prompt):
        if "RE-GROUND pass" in prompt:
            payload = self.reground
        elif "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        else:
            payload = self.review
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


def review_with(a, b, **kw):
    kw.setdefault("seat_meta", META)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(PATCH, {"seatA": a, "seatB": b}, **kw)


class CoverageTests(unittest.TestCase):
    def test_complete_coverage_recorded_and_verified(self):
        report = review_with(Seat(), Seat())
        cov = report["coverage"]
        self.assertTrue(cov["complete"], cov)
        self.assertEqual(cov["files"]["app.py"]["batches"], [1])
        self.assertEqual(
            cov["files"]["app.py"]["lenses"],
            {"correctness": [1], "operations": [1]})
        self.assertEqual(report["gate"], "pass")
        checks = {c["name"]: c
                  for c in core.verify_record(report)["checks"]}
        self.assertTrue(checks["coverage_complete"]["ok"])

    def test_failed_seat_breaks_coverage_and_degrades(self):
        report = review_with(
            Seat(), Seat(review=RuntimeError("HTTP 503 overloaded")))
        cov = report["coverage"]
        self.assertFalse(cov["complete"])
        self.assertTrue(cov["omissions"])
        self.assertTrue(report["degraded"])
        checks = {c["name"]: c
                  for c in core.verify_record(report)["checks"]}
        self.assertFalse(checks["coverage_complete"]["ok"])

    def test_old_record_without_coverage_is_not_applicable(self):
        record = {
            "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "lens": "correctness",
                 "status": "ok", "family": "google"},
                {"provider": "n", "lens": "operations",
                 "status": "ok", "family": "nvidia"}]}
        checks = {c["name"]: c
                  for c in core.verify_record(record)["checks"]}
        self.assertTrue(checks["coverage_complete"]["ok"])
        self.assertIn("not applicable",
                      checks["coverage_complete"]["detail"])


class GroundingTests(unittest.TestCase):
    def test_grounded_finding_blocks(self):
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(GOOD_QUOTE)]})
        report = review_with(a, Seat())
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["findings"][0]["grounding"],
                         "grounded")

    def test_ungrounded_finding_withdrawn_in_reground(self):
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(BOGUS_QUOTE)]},
                 reground={"status": "withdrawn",
                           "reason": "the line is not there"})
        report = review_with(a, Seat())
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(report["findings"], [])
        self.assertEqual(len(report["withdrawn_findings"]), 1)
        wf = report["withdrawn_findings"][0]
        self.assertEqual(wf["grounding"], "withdrawn")
        self.assertEqual(wf["withdrawn_by"], "seatA")
        self.assertIn("not there", wf["withdrawn_reason"])

    def test_ungrounded_finding_reground_confirmed(self):
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(BOGUS_QUOTE)]},
                 reground={"status": "confirmed",
                           "evidence_quote": GOOD_QUOTE})
        report = review_with(a, Seat())
        self.assertEqual(report["gate"], "blocked")
        f = report["findings"][0]
        self.assertEqual(f["grounding"], "reground_confirmed")
        self.assertEqual(f["evidence_quote"], GOOD_QUOTE)

    def test_unresolvable_grounding_is_inconclusive(self):
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(BOGUS_QUOTE,
                                                 sev="minor")]},
                 reground="total garbage, no json")
        b = Seat(reground="more garbage")
        report = review_with(a, b)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["findings"][0]["grounding"],
                         "unresolved")


class CrossFamilyTests(unittest.TestCase):
    def _report(self, b, meta=None):
        a = Seat(review={"verdict": "changes_requested",
                         "findings": [mk_finding(GOOD_QUOTE)]})
        return review_with(a, b, seat_meta=meta or META)

    def test_refuted_with_quote_is_disputed_and_inconclusive(self):
        b = Seat(xconfirm={"verdict": "refute",
                           "evidence_quote": GOOD_QUOTE,
                           "reason": "the caller guards it"})
        report = self._report(b)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["findings"], [])
        self.assertEqual(len(report["disputed_findings"]), 1)
        d = report["disputed_findings"][0]
        self.assertEqual(d["status"], "disputed")
        self.assertEqual(d["dispute"]["by"], "seatB")

    def test_confirmed_blocker_stands(self):
        report = self._report(Seat(xconfirm={"verdict": "confirm"}))
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["findings"][0]["cross_family"],
                         "confirmed")

    def test_refutation_without_valid_quote_does_not_dispute(self):
        b = Seat(xconfirm={"verdict": "refute",
                           "evidence_quote": BOGUS_QUOTE,
                           "reason": "trust me"})
        report = self._report(b)
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["findings"][0]["cross_family"],
                         "unresolved")
        self.assertNotIn("disputed_findings", report)

    def test_single_family_panel_cannot_confirm(self):
        meta = {"seatA": {"family": "famA", "tier": "paid"},
                "seatB": {"family": "famA", "tier": "paid"}}
        report = self._report(Seat(), meta=meta)
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["findings"][0]["cross_family"],
                         "unavailable")


class TierAttestationTests(unittest.TestCase):
    def _record(self, **over):
        record = {
            "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "lens": "correctness",
                 "status": "ok", "family": "google",
                 "tier": "free"},
                {"provider": "n", "lens": "operations",
                 "status": "ok", "family": "nvidia",
                 "tier": "paid"}]}
        record.update(over)
        return record

    def _tier_check(self, record):
        checks = {c["name"]: c
                  for c in core.verify_record(record)["checks"]}
        return checks["tier_policy"]

    def test_private_with_free_seat_fails(self):
        check = self._tier_check(self._record(private=True))
        self.assertFalse(check["ok"])

    def test_private_all_paid_passes(self):
        record = self._record(private=True)
        record["reviewer_reports"][0]["tier"] = "paid"
        self.assertTrue(self._tier_check(record)["ok"])

    def test_public_with_free_seat_passes(self):
        self.assertTrue(
            self._tier_check(self._record(private=False))["ok"])

    def test_no_declaration_is_not_applicable(self):
        check = self._tier_check(self._record())
        self.assertTrue(check["ok"])
        self.assertIn("not applicable", check["detail"])

    def test_failed_free_seat_does_not_fail(self):
        record = self._record(private=True)
        record["reviewer_reports"][0]["status"] = "error"
        self.assertTrue(self._tier_check(record)["ok"])


class PrecedentUnitTests(unittest.TestCase):
    ENTRIES = [{"finding_id": "abc123", "path": "a.py",
                "blob": "B1", "seen_in": ["r1", "r2"],
                "disposition": {"round": "r2", "file": "d.md",
                                "summary": "s"}}]

    def _finding(self):
        return {"id": "abc123", "file": "a.py",
                "severity": "minor", "title": "t",
                "sources": ["deterministic"], "consensus": False}

    def test_unchanged_blob_classifies_standing(self):
        remaining, standing = core.apply_precedents(
            [self._finding()], self.ENTRIES, lambda p: "B1")
        self.assertEqual(remaining, [])
        self.assertEqual(len(standing), 1)
        self.assertEqual(
            standing[0]["precedent"]["repeats"], 2)

    def test_changed_blob_adjudicates_fresh(self):
        remaining, standing = core.apply_precedents(
            [self._finding()], self.ENTRIES, lambda p: "B2")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(standing, [])

    def test_upsert_precedent_refreshes(self):
        out = core.upsert_precedent(
            [], self._finding(), "B1", "r3", "d3.md", "sum")
        self.assertEqual(len(out), 1)
        out = core.upsert_precedent(
            out, self._finding(), "B1", "r4", "d4.md", "sum")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["seen_in"], ["r3", "r4"])


GUARD_PATCH = (
    "diff --git a/tests/test_external_review_v071.py "
    "b/tests/test_external_review_v071.py\n"
    "--- a/tests/test_external_review_v071.py\n"
    "+++ b/tests/test_external_review_v071.py\n"
    "@@ -60,1 +60,2 @@\n"
    " class SomeTests:\n"
    "+@unittest.skipUnless(os.name == \"posix\", \"posix only\")\n")


class PrecedentIntegrationTests(unittest.TestCase):
    def test_seed_fingerprint_matches_live_deterministic_id(self):
        # The store's guard entry must key to the id the
        # deterministic layer actually mints today — otherwise
        # the seed is dead weight.
        self.assertEqual(
            core.fingerprint("tests/test_external_review_v071.py",
                             "testing", "Test disabled in added "
                                        "code"),
            "ce560a25266e")

    def _run(self, blob):
        store_path = os.path.join(
            os.path.dirname(__file__), "..", "precedents.json")
        with open(store_path, encoding="utf-8") as fh:
            store = json.load(fh)
        precedents = {
            "entries": store["entries"],
            "blob_lookup": lambda p: blob,
            "store_path": "precedents.json",
            "store_sha256": "0" * 64}
        return core.run_review(
            GUARD_PATCH, {"seatA": Seat(), "seatB": Seat()},
            seat_meta=META, sleep=lambda *_a: None,
            precedents=precedents)

    def test_guard_repeat_classified_standing(self):
        report = self._run(
            "fe3aad00815dbf21f0f5157e1ee4a7a68e424d5d")
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(len(report.get("standing_findings")
                             or []), 1)
        self.assertEqual(
            report["standing_findings"][0]["id"], "ce560a25266e")
        self.assertNotIn(
            "ce560a25266e",
            [f["id"] for f in report["findings"]])

    def test_changed_blob_keeps_finding(self):
        report = self._run("0" * 40)
        self.assertIn("ce560a25266e",
                      [f["id"] for f in report["findings"]])
        self.assertNotIn("standing_findings", report)


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
            os.makedirs(os.path.dirname(full), exist_ok=True) \
                if os.path.dirname(path) else None
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def patch_hash(self, rng):
        patch = core.collect_git_patch(self.td, range_spec=rng)
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()


class PrecedentVerifyTests(_GitRepo):
    def setUp(self):
        super().setUp()
        self.c1 = self.write_commit(
            {"guard.txt": "guarded content\n", "a.txt": "one\n"},
            "c1")
        blob = self.git("rev-parse", "HEAD:guard.txt")
        store = {"schema": core.PRECEDENTS_SCHEMA, "entries": [{
            "finding_id": "fid1", "path": "guard.txt",
            "blob": blob, "seen_in": ["r1"],
            "disposition": {"round": "r1", "file": "d.md",
                            "summary": "s"}}]}
        self.store_bytes = json.dumps(store).encode("utf-8")
        self.c1 = self.write_commit(
            {"precedents.json":
             self.store_bytes.decode("utf-8")}, "c1b")
        self.c2 = self.write_commit({"a.txt": "one\ntwo\n"}, "c2")
        self.rng = f"{self.c1}..{self.c2}"
        self.standing = [{
            "id": "fid1", "file": "guard.txt",
            "severity": "minor", "title": "t",
            "sources": ["deterministic"], "consensus": False,
            "standing": True,
            "precedent": {"blob": blob, "repeats": 1,
                          "disposition": {"round": "r1",
                                          "file": "d.md",
                                          "summary": "s"}}}]
        self.record = {
            "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {"provider": "g", "lens": "correctness",
                 "status": "ok", "family": "google"},
                {"provider": "n", "lens": "operations",
                 "status": "ok", "family": "nvidia"}],
            "range": self.rng, "head": self.c2,
            "patch_sha256": self.patch_hash(self.rng),
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

    def test_valid_precedent_scope_passes(self):
        self.assertTrue(self._check(self.record)["ok"],
                        self._check(self.record))

    def test_tampered_link_fails(self):
        self.record["standing_findings"][0]["precedent"]["blob"] \
            = "0" * 40
        self.assertFalse(self._check(self.record)["ok"])

    def test_changed_cited_file_fails(self):
        self.write_commit({"guard.txt": "edited content\n"}, "c3")
        self.record["head"] = self.git("rev-parse", "HEAD")
        self.assertFalse(self._check(self.record)["ok"])


class ChainTests(_GitRepo):
    def setUp(self):
        super().setUp()
        self.c1 = self.write_commit({"a.txt": "one\n"}, "c1")
        self.c2 = self.write_commit({"a.txt": "one\ntwo\n"}, "c2")
        self.c3 = self.write_commit(
            {"a.txt": "one\ntwo\nthree\n"}, "c3")
        self.finding = {"id": "f123", "severity": "major",
                        "file": "a.txt", "title": "a defect",
                        "sources": ["seatA"], "consensus": False}
        reports = [
            {"provider": "g", "lens": "correctness",
             "status": "ok", "family": "google", "tier": "free"},
            {"provider": "n", "lens": "operations",
             "status": "ok", "family": "nvidia", "tier": "paid"}]
        self.round1 = {
            "mode": "review", "gate": "blocked", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": reports,
            "coverage": {"complete": True, "batch_count": 1,
                         "files": {}},
            "findings": [self.finding],
            "range": f"{self.c1}..{self.c2}", "head": self.c2,
            "patch_sha256": self.patch_hash(
                f"{self.c1}..{self.c2}")}
        self.verify = {
            "mode": "verify", "gate": "pass", "degraded": False,
            "test_results": [{"command": "t", "ok": True}],
            "reviewer_reports": [
                {k: v for k, v in r.items() if k != "lens"}
                for r in reports],
            "cleared": [{**self.finding,
                         "cleared_by": ["fixed", "fixed"]}],
            "remaining": [], "unjudged": [], "findings": [],
            "range": f"{self.c2}..{self.c3}", "head": self.c3,
            "patch_sha256": self.patch_hash(
                f"{self.c2}..{self.c3}")}

    def _chain(self, records):
        return core.verify_chain(records, repo=self.td,
                                 record_dirs=["r1", "r2", "r3",
                                              "r4", "r5", "r6"])

    def test_eligible_chain(self):
        result = self._chain([self.round1, self.verify])
        self.assertTrue(result["eligible"], result["checks"])
        self.assertEqual(result["warnings"], [])

    def test_gap_in_ranges_fails(self):
        self.verify["range"] = f"{self.c1}..{self.c3}"
        result = self._chain([self.round1, self.verify])
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"]
                  if not c["ok"]}
        self.assertIn("ranges_contiguous", failed)

    def test_undispositioned_round1_finding_fails(self):
        self.verify["cleared"] = []
        result = self._chain([self.round1, self.verify])
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"]
                  if not c["ok"]}
        self.assertIn("round1_findings_dispositioned", failed)

    def test_missing_round1_coverage_fails(self):
        del self.round1["coverage"]
        result = self._chain([self.round1, self.verify])
        self.assertFalse(result["eligible"])
        failed = {c["name"] for c in result["checks"]
                  if not c["ok"]}
        self.assertIn("round1_coverage_complete", failed)

    def test_budget_breach_warns_without_failing(self):
        commits = [self.c3]
        for i in range(4, 7):
            commits.append(self.write_commit(
                {"a.txt": "x\n" * i}, f"c{i}"))
        rounds = []
        prev = self.c2
        cleared = [{**self.finding,
                    "cleared_by": ["fixed", "fixed"]}]
        for head in commits:
            rng = f"{prev}..{head}"
            rounds.append({
                "mode": "verify", "gate": "pass",
                "degraded": False,
                "test_results": [{"command": "t", "ok": True}],
                "reviewer_reports": self.verify[
                    "reviewer_reports"],
                "cleared": cleared, "remaining": [],
                "unjudged": [], "findings": [],
                "range": rng, "head": head,
                "patch_sha256": self.patch_hash(rng)})
            cleared = []
            prev = head
        result = self._chain([self.round1] + rounds)
        self.assertTrue(result["eligible"], result["checks"])
        warn_names = {w["name"] for w in result["warnings"]}
        self.assertIn("convergence_budget", warn_names)

    def test_chain_cli_exit_zero(self):
        for name, record in (("r1", self.round1),
                             ("r2", self.verify)):
            d = os.path.join(self.td, name)
            os.makedirs(d)
            with open(os.path.join(d, "rec.json"), "w") as fh:
                json.dump(record, fh)
        env = dict(os.environ, HOME="/home/hatch",
                   PYTHONPATH=os.path.join(
                       os.path.dirname(__file__), "..", "src"))
        proc = subprocess.run(
            [sys.executable, "-m", "codereview.cli",
             "record-verify", "--chain",
             os.path.join(self.td, "r1"),
             os.path.join(self.td, "r2"),
             "--repo", self.td],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("ELIGIBLE", proc.stdout)


class FixtureExpectedCountTests(unittest.TestCase):
    FX_PATCH = (
        "diff --git a/fixtures/case1.py b/fixtures/case1.py\n"
        "--- a/fixtures/case1.py\n"
        "+++ b/fixtures/case1.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+SPECIMEN = True\n")

    def _run(self, expected):
        a = Seat(review={
            "verdict": "changes_requested",
            "findings": [mk_finding("SPECIMEN = True", sev="minor",
                                    title="Specimen looks odd",
                                    file="fixtures/case1.py")]})
        scope = {"patterns": ["fixtures/**"],
                 "expected_counts": expected,
                 "policy_version": 1,
                 "manifest_path": "m.json",
                 "manifest_sha256": "0" * 64}
        return core.run_review(
            self.FX_PATCH, {"seatA": a, "seatB": Seat()},
            seat_meta=META, sleep=lambda *_a: None,
            fixture_scope=scope)

    def test_zero_expected_count_keeps_finding_as_product(self):
        report = self._run({"fixtures/**": 0})
        self.assertEqual(
            [f["file"] for f in report["findings"]],
            ["fixtures/case1.py"])
        self.assertEqual(report["fixture_findings"], [])
        self.assertEqual(
            report["fixture_scope"]["excess"][0]["expected"], 0)

    def test_within_expected_count_classifies(self):
        report = self._run({"fixtures/**": 3})
        self.assertEqual(len(report["fixture_findings"]), 1)
        self.assertEqual(report["findings"], [])


class BatchSectionsDetailedTests(unittest.TestCase):
    """Direct unit coverage for the coverage ledger the batches
    carry (internal review of this release, minor a5f0ac58e716):
    file tracking, per-file dedupe across sections, and the
    truncation flag's interaction with the ledger."""

    def test_file_ledger_and_dedupe(self):
        sections = [("a.py", "x" * 30), ("b.py", "y" * 30),
                    ("a.py", "z" * 10)]
        batches, batch_files, truncated = \
            core._batch_sections_detailed(sections, 50)
        self.assertFalse(truncated)
        self.assertEqual(batch_files, [["a.py"], ["b.py", "a.py"]])
        self.assertEqual("".join(batches),
                         "x" * 30 + "y" * 30 + "z" * 10)

    def test_oversized_section_truncates_and_flags(self):
        sections = [("big.py", "x" * 500)]
        batches, batch_files, truncated = \
            core._batch_sections_detailed(sections, 100)
        self.assertTrue(truncated)
        self.assertEqual(batch_files, [["big.py"]])
        self.assertIn("section truncated", batches[0])


class HousekeepingTests(unittest.TestCase):
    def test_doctor_states_live_probe_rule(self):
        result = core.run_doctor({"a": lambda prompt: "{}"})
        self.assertIn("exact review call shape", result["rule"])

    def test_verification_record_carries_attestation(self):
        prior = {"gate": "blocked", "findings": [{
            "id": "det1", "severity": "blocker", "file": "x.py",
            "title": "t", "sources": ["deterministic"],
            "consensus": False}]}
        ok = lambda prompt: json.dumps(  # noqa: E731
            {"resolutions": [{"finding_id": "det1",
                              "status": "fixed",
                              "evidence": "clean diff fixed"}],
             "new_findings": []})
        report = core.run_verification(
            "diff --git a/x.py b/x.py\n+++ b/x.py\n"
            "@@ -1,1 +1,1 @@\n+clean = True\n",
            {"a": ok, "b": ok}, prior, "fixed it",
            test_results=[{"command": "t", "ok": True}],
            record_extra={"range": "A..B", "head": "B"},
            private=True)
        self.assertEqual(report["gate"], "pass")
        self.assertEqual(report["test_results"],
                         [{"command": "t", "ok": True}])
        self.assertEqual(report["range"], "A..B")
        self.assertIs(report["private"], True)


if __name__ == "__main__":
    unittest.main()
