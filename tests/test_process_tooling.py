"""Process tooling (open-refutations solution §5, owner-adopted
2026-11-04): the computed dispute inventory (§5.1), the
append-only disposition store and record-verify's consultation
of it (§5.2), the release-flow freshness check (§5.3), the
deterministic authority-affecting tagger (§5.5), and quote
anchoring — line_basis at raise time and `locate` (§5.6).

All fixtures are synthetic records and real temporary git
repositories, in the established suite style."""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, disputes  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, timeout=60)


def _make_repo(path):
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "Test")
    return path


def _commit(repo, files, message="c"):
    for name, text in files.items():
        full = os.path.join(repo, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                         check=True, capture_output=True,
                         timeout=60)
    return out.stdout.decode().strip()


def _entry(fid, **kw):
    base = {"finding_id": fid, "type": "sustain_refutation",
            "decider": "owner", "date": "2026-11-04"}
    base.update(kw)
    return base


FID_A = "aaaaaaaaaaa1"
FID_B = "bbbbbbbbbbb2"
FID_C = "ccccccccccc3"


# ------------------------------------------------------------ tagger

class TaggerTests(unittest.TestCase):
    def tag(self, title, file="src/codereview/core.py",
            category="correctness"):
        return disputes.tag_authority(
            {"id": FID_A, "title": title, "file": file,
             "category": category})

    def test_precedent_key_is_authority(self):
        tag = self.tag("Function-level precedent can match the "
                       "wrong callee when scopes share a name")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_VALIDITY, tag["dimensions"])

    def test_family_attribution_is_authority(self):
        tag = self.tag("Family tag not set for seats built from "
                       "custom specs", file="src/codereview/"
                                            "providers.py")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_INDEPENDENCE, tag["dimensions"])

    def test_role_assignment_is_authority(self):
        tag = self.tag("Role assignment can record the wrong "
                       "seat on duplicate names",
                       file="src/codereview/cli.py")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_WHO_DECIDES, tag["dimensions"])

    def test_quorum_and_coverage_are_authority(self):
        tag = self.tag("Verification quorum can pass with one "
                       "reviewer; coverage accounting agrees")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_ELIGIBILITY, tag["dimensions"])

    def test_redaction_and_private_are_authority(self):
        tag = self.tag("--private flag interacts unsafely with "
                       "free-tier seats; redaction is skipped",
                       file="CHANGELOG.md")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_EGRESS, tag["dimensions"])

    def test_attempts_ledger_path_is_authority(self):
        tag = self.tag("Committed attempts log leaks internal "
                       "provider telemetry",
                       file="gate-attempts.jsonl")
        self.assertTrue(tag["authority_affecting"])
        self.assertIn(disputes.DIM_EGRESS, tag["dimensions"])

    def test_prompt_truncation_is_not_authority(self):
        # The §5.5 exclusion, verbatim case: _finding_public
        # slices evidence for prompts; storage is full-text.
        tag = self.tag("_finding_public truncates evidence to "
                       "2000 chars for prompts, risking mid-word "
                       "cuts")
        self.assertFalse(tag["authority_affecting"])
        self.assertTrue(any("excluded" in r
                            for r in tag["reasons"]))

    def test_renderer_summary_is_not_authority(self):
        tag = self.tag("Verification summary undercounts cleared "
                       "blockers versus the source record",
                       file="review-v15/record.md")
        self.assertFalse(tag["authority_affecting"])
        tag2 = self.tag("Reviewer success count contradicts "
                        "degraded status in the same gate line",
                        file="review-v15/record.md")
        self.assertFalse(tag2["authority_affecting"])

    def test_plain_defect_is_not_authority(self):
        tag = self.tag("build_providers does not apply model "
                       "override from preset:model spec",
                       file="src/codereview/providers.py")
        self.assertFalse(tag["authority_affecting"])

    def test_manual_overrides_win_both_ways(self):
        plain = {"id": FID_B, "title": "Nearest-rank percentile "
                                       "indexes past the end",
                 "file": "src/codereview/bench.py",
                 "category": "correctness"}
        forced = disputes.tag_authority(
            plain, {"authority": [FID_B]})
        self.assertTrue(forced["authority_affecting"])
        loud = {"id": FID_C,
                "title": "Precedent lookup uses stale lines",
                "file": "src/codereview/core.py",
                "category": "correctness"}
        muted = disputes.tag_authority(
            loud, {"not_authority": [FID_C]})
        self.assertFalse(muted["authority_affecting"])


# ------------------------------------------------------------ store

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "dispositions.jsonl")

    def test_append_creates_header_and_round_trips(self):
        stored = disputes.append_entry(self.store, _entry(FID_A))
        self.assertEqual(stored["marker"], "ratified")
        with open(self.store, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(json.loads(lines[0])["schema"],
                         disputes.DISPOSITIONS_SCHEMA)
        loaded = disputes.load_store(self.store)
        self.assertEqual(loaded["problems"], [])
        self.assertEqual(len(loaded["entries"]), 1)
        self.assertEqual(loaded["entries"][0]["finding_id"],
                         FID_A)
        self.assertIn(FID_A,
                      disputes.dispositioned_ids(loaded["entries"]))

    def test_duplicate_disposition_rejected(self):
        disputes.append_entry(self.store, _entry(FID_A))
        with self.assertRaises(ValueError):
            disputes.append_entry(self.store, _entry(FID_A))

    def test_override_must_name_a_real_prior_entry(self):
        first = disputes.append_entry(self.store, _entry(FID_A))
        good = _entry(FID_A, marker="override",
                      supersedes=disputes.entry_hash(first),
                      type="split", reason_corrected="the guard "
                      "upstream makes it unreachable")
        stored = disputes.append_entry(self.store, good)
        self.assertEqual(stored["type"], "split")
        self.assertEqual(
            len(disputes.load_store(self.store)["entries"]), 2)
        # A second override naming a hash that is not a prior
        # entry for this finding is rejected.
        bad = _entry(FID_A, marker="override",
                     supersedes="0" * 64)
        with self.assertRaises(ValueError):
            disputes.append_entry(self.store, bad)
        # And any non-override second entry stays rejected even
        # after an override exists.
        with self.assertRaises(ValueError):
            disputes.append_entry(self.store, _entry(FID_A))

    def test_override_without_supersedes_rejected(self):
        disputes.append_entry(self.store, _entry(FID_A))
        with self.assertRaises(ValueError):
            disputes.append_entry(
                self.store, _entry(FID_A, marker="override"))

    def test_fixed_requires_commit(self):
        with self.assertRaises(ValueError):
            disputes.append_entry(
                self.store, _entry(FID_A, type="fixed"))
        ok = disputes.append_entry(
            self.store, _entry(FID_A, type="fixed",
                               commit="abc1234"))
        self.assertEqual(ok["commit"], "abc1234")

    def test_field_validation(self):
        for bad in (
                _entry("not-a-fingerprint"),
                _entry(FID_A, type="ruled"),
                _entry(FID_A, decider="builder"),
                _entry(FID_A, date="yesterday"),
                _entry(FID_A, reason_check="plausible"),
                _entry(FID_A, basis_evidence=["short"]),
                _entry(FID_A, marker="sealed")):
            with self.assertRaises(ValueError, msg=str(bad)):
                disputes.append_entry(self.store, bad)
        ok = disputes.append_entry(
            self.store, _entry(
                FID_A, reason_check="contradicted",
                reason_corrected="unreachable: the walker "
                                 "guards isinstance first",
                basis_evidence=["a" * 64]))
        self.assertEqual(ok["reason_check"], "contradicted")

    def test_corrupt_store_is_never_appended_to(self):
        with open(self.store, "w", encoding="utf-8") as fh:
            fh.write('{"schema": "codereview.dispositions/1"}\n')
            fh.write('this is not json\n')
        loaded = disputes.load_store(self.store)
        self.assertTrue(loaded["problems"])
        with self.assertRaises(ValueError):
            disputes.append_entry(self.store, _entry(FID_A))

    def test_missing_store_is_empty_not_an_error(self):
        loaded = disputes.load_store(self.store)
        self.assertEqual(loaded, {"entries": [], "problems": []})


# ------------------------------------------------------------ inventory

def _dispute_record():
    finding = {
        "id": FID_A, "severity": "major",
        "category": "correctness", "file": "src/codereview/"
        "core.py", "line": 100, "title": "Precedent lookup uses "
        "a stale line", "status": "disputed",
        "sources": ["seatA"], "evidence_complete": True,
        "dispute": {"by": "seatB", "family": "famB",
                    "raiser_family": "famA",
                    "evidence_quote": "x = 1", "reason": "no",
                    "adequacy": "strong"}}
    weak = {
        "id": FID_B, "severity": "major", "category": "quality",
        "file": "src/codereview/bench.py", "line": 5,
        "title": "Percentile indexes past the end",
        "status": "refutation_weak", "sources": ["seatA"],
        "dispute": {"by": "seatB", "family": "famB",
                    "raiser_family": "famA",
                    "evidence_quote": "y = 2", "reason": "no",
                    "adequacy": "weak"}}
    standing = {"id": FID_C, "severity": "minor",
                "category": "quality", "file": "x.py",
                "title": "a standing finding"}
    return {
        "schema": "codereview.report/1", "mode": "review",
        "gate": "inconclusive", "head": "abc123",
        "range": "a..b",
        "findings": [dict(standing)],
        "disputed_findings": [finding],
        # The same finding serialized twice, as merged records
        # do: the inventory must count it once.
        "reviewer_reports": [
            {"provider": "seatA", "lens": "correctness",
             "status": "ok", "family": "famA",
             "findings": [dict(finding)]}],
        "refutation_weak_findings": [weak]}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rdir = os.path.join(self.tmp, "review-t1")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(_dispute_record(), fh)

    def test_inventory_counts_each_dispute_once(self):
        inv = disputes.build_inventory(self.tmp, [])
        self.assertEqual(inv["records_scanned"], 1)
        self.assertEqual({r["id"] for r in inv["open"]},
                         {FID_A, FID_B})
        row = next(r for r in inv["open"] if r["id"] == FID_A)
        self.assertEqual(row["lens"], "correctness")
        self.assertEqual(row["raiser_family"], "famA")
        self.assertEqual(row["refuter_family"], "famB")
        self.assertEqual(row["adequacy"], "strong")
        self.assertTrue(
            row["authority"]["authority_affecting"])

    def test_store_entry_moves_dispute_to_dispositioned(self):
        inv = disputes.build_inventory(
            self.tmp, [_entry(FID_A)])
        self.assertEqual([r["id"] for r in inv["open"]], [FID_B])
        self.assertEqual(
            [r["id"] for r in inv["dispositioned"]], [FID_A])

    def test_inventory_dedupes_across_records(self):
        # The same record file present under two review-*/
        # directories (a copied record) is one set of disputes,
        # not two (0bb1b939ab67).
        rdir = os.path.join(self.tmp, "review-t2")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(_dispute_record(), fh)
        inv = disputes.build_inventory(self.tmp, [])
        self.assertEqual(inv["records_scanned"], 2)
        self.assertEqual({r["id"] for r in inv["open"]},
                         {FID_A, FID_B})
        self.assertEqual(len(inv["open"]), 2)


# ------------------------------------------------------------ freshness

class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = _make_repo(os.path.join(self.tmp, "repo"))
        self.c1 = _commit(self.repo, {"app.py": "x = 1\n"},
                          "one")
        self.c2 = _commit(self.repo, {"app.py": "x = 2\n"},
                          "two")
        rec = _dispute_record()
        rec["range"] = f"{self.c1}..{self.c2}"
        rec["head"] = self.c2
        rdir = os.path.join(self.repo, "review-t1")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(rec, fh)
        self.span = f"{self.c1}..{self.c2}"

    def test_check_flags_uninventoried_dispute_in_span(self):
        result = disputes.check_freshness(
            self.repo, self.repo, self.span, [], set())
        self.assertEqual(
            {r["id"] for r in result["violations"]},
            {FID_A, FID_B})

    def test_check_passes_when_inventoried(self):
        result = disputes.check_freshness(
            self.repo, self.repo, self.span, [],
            {FID_A, FID_B})
        self.assertEqual(result["violations"], [])

    def test_check_passes_when_dispositioned(self):
        result = disputes.check_freshness(
            self.repo, self.repo, self.span,
            [_entry(FID_A), _entry(FID_B)], set())
        self.assertEqual(result["violations"], [])

    def test_record_outside_span_is_not_checked(self):
        result = disputes.check_freshness(
            self.repo, self.repo, f"{self.c2}..{self.c2}",
            [], set())
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["touching"], [])

    def test_degenerate_range_record_checked_via_head(self):
        # A record whose range is the degenerate X..X (rev-list
        # yields an empty set) still takes part in the check
        # through its recorded head, instead of being silently
        # skipped (55c815ff5fbe).
        rec = _dispute_record()
        rec["range"] = f"{self.c2}..{self.c2}"
        rec["head"] = self.c2
        rdir = os.path.join(self.repo, "review-t2")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(rec, fh)
        result = disputes.check_freshness(
            self.repo, self.repo, self.span, [], set())
        self.assertIn("review-t2/rec.json", result["touching"])
        self.assertEqual(
            {r["id"] for r in result["violations"]},
            {FID_A, FID_B})

    def test_degenerate_range_without_head_is_unscoped(self):
        rec = {"schema": "codereview.report/1",
               "range": f"{self.c2}..{self.c2}"}
        rdir = os.path.join(self.repo, "review-t3")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(rec, fh)
        touching, unscoped = disputes.records_touching_span(
            self.repo, self.repo, self.span)
        self.assertIn("review-t3/rec.json", unscoped)
        self.assertNotIn("review-t3/rec.json", touching)

    def test_span_scan_caches_range_specs(self):
        # Records sharing the span's own range spec cost no
        # rev-list beyond the span resolution itself
        # (e9ef62daa1a0).
        rec = _dispute_record()
        rec["range"] = self.span
        rec["head"] = self.c2
        rdir = os.path.join(self.repo, "review-t4")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(rec, fh)
        calls = []
        real = disputes._git_lines

        def counting(repo, *args):
            calls.append(args)
            return real(repo, *args)

        disputes._git_lines = counting
        try:
            disputes.records_touching_span(
                self.repo, self.repo, self.span)
        finally:
            disputes._git_lines = real
        revlists = [a for a in calls if a[0] == "rev-list"]
        self.assertEqual(
            revlists.count(("rev-list", self.span)), 1)

    def test_cli_check_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["disputes", "--repo", self.repo,
                           "--check", "--span", self.span])
        self.assertEqual(rc, 1)
        inv_file = os.path.join(self.tmp, "inv.json")
        with open(inv_file, "w", encoding="utf-8") as fh:
            json.dump({"open": [{"id": FID_A}, {"id": FID_B}]},
                      fh)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["disputes", "--repo", self.repo,
                           "--check", "--span", self.span,
                           "--inventory", inv_file])
        self.assertEqual(rc, 0)


# ------------------------------------------------------------ verify

class VerifyConsultsStoreTests(unittest.TestCase):
    def _record_with_dispute(self):
        return {"schema": "codereview.report/1",
                "mode": "review", "gate": "inconclusive",
                "degraded": False, "test_results": [],
                "reviewer_reports": [], "findings": [],
                "disputed_findings": [{
                    "id": FID_A, "severity": "major",
                    "category": "correctness", "file": "a.py",
                    "line": 1, "title": "a dispute",
                    "status": "disputed"}]}

    def test_verify_record_without_store_is_legacy(self):
        result = core.verify_record(self._record_with_dispute())
        names = [c["name"] for c in result["checks"]]
        self.assertNotIn("disputes_dispositioned", names)
        self.assertNotIn("dispositions_consumed", result)

    def test_verify_record_with_store_both_ways(self):
        rec = self._record_with_dispute()
        empty = core.verify_record(rec, dispositions=[])
        check = next(c for c in empty["checks"]
                     if c["name"] == "disputes_dispositioned")
        self.assertFalse(check["ok"])
        self.assertEqual(empty["dispositions_consumed"], [])
        filled = core.verify_record(
            rec, dispositions=[_entry(FID_A)])
        check = next(c for c in filled["checks"]
                     if c["name"] == "disputes_dispositioned")
        self.assertTrue(check["ok"])
        self.assertEqual(
            [e["finding_id"] for e in
             filled["dispositions_consumed"]], [FID_A])

    def test_verify_chain_counts_store_disposition(self):
        r1 = {"schema": "codereview.report/1", "mode": "review",
              "gate": "blocked", "degraded": False,
              "findings": [{
                  "id": FID_A, "severity": "major",
                  "category": "correctness", "file": "a.py",
                  "line": 1, "title": "a dispute",
                  "status": "disputed"}],
              "reviewer_reports": [], "test_results": []}
        r2 = {"schema": "codereview.report/1", "mode": "verify",
              "gate": "pass", "degraded": False, "cleared": [],
              "reviewer_reports": [],
              "test_results": [{"ok": True, "command": "true"}]}
        bare = core.verify_chain([r1, r2])
        check = next(c for c in bare["checks"] if c["name"]
                     == "round1_findings_dispositioned")
        self.assertFalse(check["ok"])
        self.assertNotIn("dispositions_consumed", bare)
        with_store = core.verify_chain(
            [r1, r2], dispositions=[_entry(FID_A)])
        check = next(c for c in with_store["checks"]
                     if c["name"]
                     == "round1_findings_dispositioned")
        self.assertTrue(check["ok"], check["detail"])
        self.assertEqual(
            [e["finding_id"] for e in
             with_store["dispositions_consumed"]], [FID_A])


# ------------------------------------------------------------ locate

class LocateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = _make_repo(os.path.join(self.tmp, "repo"))
        # The validated quote is a long line so its sidecar is
        # genuinely truncated in the record's display copy.
        self.long_line = "# " + ("evidence " * 60) + "end"
        app = "x = 1\n" + self.long_line + "\ny = 2\n"
        self.head = _commit(self.repo, {"app.py": app}, "one")

    def _write_record(self, record):
        rdir = os.path.join(self.repo, "review-loc")
        os.makedirs(rdir, exist_ok=True)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(record, fh)
        return "review-loc"

    def test_locate_resolves_sidecar_quote_to_blob_line(self):
        digest = hashlib.sha256(
            self.long_line.encode("utf-8")).hexdigest()
        record = {
            "schema": "codereview.report/1", "mode": "review",
            "head": self.head, "findings": [{
                "id": FID_A, "severity": "major",
                "category": "correctness", "file": "app.py",
                # Cited line deliberately wrong (7 vs the real
                # 2): the quote, not the number, is the anchor.
                "line": 7, "title": "a claim about the long line",
                "status": "disputed", "evidence_quote": "",
                "dispute": {
                    "by": "seatB", "family": "famB",
                    "raiser_family": "famA",
                    "evidence_quote": self.long_line[:400],
                    "evidence_quote_ref": {
                        "sha256": digest,
                        "length": len(self.long_line),
                        "truncated": True},
                    "reason": "no", "adequacy": "strong"}}]}
        rdir = self._write_record(record)
        ev = os.path.join(self.repo, rdir, "evidence")
        os.makedirs(ev)
        with open(os.path.join(ev, digest), "w",
                  encoding="utf-8") as fh:
            fh.write(self.long_line)
        result = disputes.locate_finding(
            record, FID_A, self.repo, rdir)
        self.assertEqual(result["positions"], [2])
        self.assertEqual(result["quote_source"], "dispute")
        self.assertEqual(result["quote_from"], "sidecar")
        self.assertFalse(result["cited_matches"])
        self.assertIsNone(result["line_basis"])

    def test_locate_legacy_record_without_head_or_basis(self):
        record = {
            "schema": "codereview.report/1", "mode": "review",
            "findings": [{
                "id": FID_B, "severity": "minor",
                "category": "quality", "file": "app.py",
                "line": 1, "title": "first line",
                "evidence_quote": "x = 1"}]}
        self._write_record(record)
        result = disputes.locate_finding(
            record, FID_B, self.repo, "review-loc")
        self.assertEqual(result["blob_ref"], "HEAD")
        self.assertEqual(result["positions"], [1])
        self.assertTrue(result["cited_matches"])

    def test_locate_unknown_finding_returns_none(self):
        record = {"schema": "codereview.report/1",
                  "findings": []}
        self.assertIsNone(disputes.locate_finding(
            record, FID_A, self.repo, "review-loc"))


# ------------------------------------------------------------ line basis

PATCH_BASIS = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -9,2 +9,3 @@\n"
    " ctx = 1\n"
    "+VALUE = compute(items)\n"
    " tail = 2\n")
# In PATCH_BASIS the VALUE line is new-side line 10 and
# diff-relative index 6 — the two numberings disagree, so a
# citation is determinable either way.


class LineBasisTests(unittest.TestCase):
    def test_deterministic_findings_carry_blob_basis(self):
        patch = ("diff --git a/app.py b/app.py\n"
                 "--- a/app.py\n"
                 "+++ b/app.py\n"
                 "@@ -1,1 +1,1 @@\n"
                 "+VALUE = eval(input)\n")
        findings = core.deterministic_scan(patch)
        self.assertTrue(findings)
        for f in findings:
            self.assertEqual(f["line_basis"], "blob")

    def test_apply_line_basis_distinguishes_numberings(self):
        quote = "VALUE = compute(items)"
        blob = {"file": "app.py", "line": 10,
                "evidence_quote": quote}
        diff = {"file": "app.py", "line": 6,
                "evidence_quote": quote}
        other = {"file": "app.py", "line": 42,
                 "evidence_quote": quote}
        core._apply_line_basis([blob, diff, other], PATCH_BASIS)
        self.assertEqual(blob["line_basis"], "blob")
        self.assertEqual(diff["line_basis"], "diff")
        self.assertNotIn("line_basis", other)

    def test_apply_line_basis_ambiguous_is_left_unset(self):
        # Hunk starting at new line 5: the first content line
        # sits at new-side 5 AND diff index 5 — both numberings
        # claim it, so no basis may be recorded.
        patch = ("diff --git a/app.py b/app.py\n"
                 "--- a/app.py\n"
                 "+++ b/app.py\n"
                 "@@ -5,1 +5,1 @@\n"
                 " only = line\n")
        f = {"file": "app.py", "line": 5,
             "evidence_quote": "only = line"}
        core._apply_line_basis([f], patch)
        self.assertNotIn("line_basis", f)


# ------------------------------------------------------------ run summary

_STEP4_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,4 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n"
    "+RESULT = VALUE * 2\n")


class _Seat:
    def __init__(self, review=None, xconfirm=None):
        self.review = review or {"verdict": "pass",
                                 "summary": "ok", "findings": []}
        self.xconfirm = xconfirm or {"verdict": "confirm"}

    def __call__(self, prompt):
        if "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        elif "RE-GROUND pass" in prompt:
            payload = {"status": "withdrawn",
                       "reason": "cannot support it"}
        else:
            payload = self.review
        return json.dumps(payload)


class RunSummaryTests(unittest.TestCase):
    def test_open_disputes_summary_and_line_basis_in_record(self):
        title = "Total computed without a guard"
        raiser = _Seat(review={
            "verdict": "changes_requested",
            "findings": [{
                "severity": "major", "category": "correctness",
                "file": "app.py", "line": 2, "title": title,
                "evidence": "VALUE = compute_total(items)",
                "evidence_quote": "VALUE = compute_total(items)",
                "recommendation": "guard it",
                "confidence": 0.9}]})
        refuter = _Seat(xconfirm={
            "verdict": "refute",
            "evidence_quote": "VALUE = compute_total(items)",
            "reason": "the claim is wrong"})
        meta = {"seatA": {"family": "famA", "tier": "paid"},
                "seatB": {"family": "famB", "tier": "paid"}}
        rec = core.run_review(
            _STEP4_PATCH, {"seatA": raiser, "seatB": refuter},
            seat_meta=meta, sleep=lambda *_a: None)
        fid = core.fingerprint("app.py", "correctness", title)
        self.assertEqual(rec["open_disputes"],
                         {"count": 1, "ids": [fid]})
        weak = rec["refutation_weak_findings"][0]
        # Cited line 2 is the quote's new-side position (its
        # diff index is 6): the basis is determinable as blob.
        self.assertEqual(weak["line_basis"], "blob")

    def test_open_disputes_empty_on_clean_run(self):
        rec = core.run_review(
            _STEP4_PATCH,
            {"seatA": _Seat(), "seatB": _Seat()},
            seat_meta={"seatA": {"family": "famA",
                                 "tier": "paid"},
                       "seatB": {"family": "famB",
                                 "tier": "paid"}},
            sleep=lambda *_a: None)
        self.assertEqual(rec["open_disputes"],
                         {"count": 0, "ids": []})


# ------------------------------------------------------------ CLI

class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rdir = os.path.join(self.tmp, "review-t1")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(_dispute_record(), fh)
        self.store = os.path.join(self.tmp, "dispositions.jsonl")

    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(argv)
        return rc, out.getvalue()

    def test_disputes_json_output(self):
        rc, out = self._run(["disputes", "--repo", self.tmp,
                             "--store", self.store, "--json"])
        self.assertEqual(rc, 0)
        inv = json.loads(out)
        self.assertEqual({r["id"] for r in inv["open"]},
                         {FID_A, FID_B})

    def test_disputes_record_appends_then_rejects_duplicate(self):
        entry_file = os.path.join(self.tmp, "entry.json")
        with open(entry_file, "w", encoding="utf-8") as fh:
            json.dump(_entry(FID_A), fh)
        rc, _out = self._run(["disputes", "--repo", self.tmp,
                              "--store", self.store,
                              "--record", entry_file])
        self.assertEqual(rc, 0)
        rc, out = self._run(["disputes", "--repo", self.tmp,
                             "--store", self.store, "--json"])
        inv = json.loads(out)
        self.assertEqual([r["id"] for r in inv["open"]], [FID_B])
        rc, _out = self._run(["disputes", "--repo", self.tmp,
                              "--store", self.store,
                              "--record", entry_file])
        self.assertEqual(rc, 2)

    def test_locate_cli_on_plain_record(self):
        repo = _make_repo(os.path.join(self.tmp, "repo2"))
        head = _commit(repo, {"app.py": "x = 1\ny = 2\n"}, "one")
        record = {"schema": "codereview.report/1",
                  "mode": "review", "head": head,
                  "findings": [{
                      "id": FID_A, "severity": "minor",
                      "category": "quality", "file": "app.py",
                      "line": 2, "title": "second line",
                      "evidence_quote": "y = 2"}]}
        rdir = os.path.join(repo, "review-l1")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(record, fh)
        rc, out = self._run(["locate", FID_A, "--record", rdir,
                             "--repo", repo])
        self.assertEqual(rc, 0)
        self.assertIn("[2]", out)


if __name__ == "__main__":
    unittest.main()
