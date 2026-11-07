"""Phase 6 follow-up pins (external test pass, 2026-11-06).

Each class pins one Phase 6 item as fixed on the master the
rerun verified. The tester's scripts live outside the repo;
these are the in-repo equivalents of her repros.
"""

import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "src"))

from codereview import core  # noqa: E402

UNICODE_PATH = "src/日本語/ü ñ.py"


def _quoted(path):
    """The C-quoted form git emits for a path whose bytes are
    not bare-safe: octal escapes for every non-ASCII byte."""
    out = []
    for b in path.encode("utf-8"):
        if 32 <= b < 127 and b not in (34, 92):
            out.append(chr(b))
        else:
            out.append("\\%03o" % b)
    return '"' + "".join(out) + '"'


class TestP604QuotedPaths(unittest.TestCase):
    """P6-04: paths git C-quotes (non-ASCII, tab, quote) were
    attributed to the file 'unknown'; the parser now decodes
    the quoted form everywhere paths are read from a patch."""

    def test_quoted_unicode_path_in_sections(self):
        q = _quoted("a/" + UNICODE_PATH)
        qb = _quoted("b/" + UNICODE_PATH)
        patch = (f"diff --git {q} {qb}\n--- {q}\n+++ {qb}\n"
                 "@@ -0,0 +1 @@\n+x = 1\n")
        sections = core.split_patch_sections(patch)
        self.assertEqual([n for n, _ in sections],
                         [UNICODE_PATH])

    def test_quoted_tab_and_quote_paths(self):
        patch = (
            'diff --git "a/tab\\tname.py" "b/tab\\tname.py"\n'
            '--- "a/tab\\tname.py"\n+++ "b/tab\\tname.py"\n'
            "@@ -0,0 +1 @@\n+t\n"
            'diff --git "a/q\\"uote.py" "b/q\\"uote.py"\n'
            '--- "a/q\\"uote.py"\n+++ "b/q\\"uote.py"\n'
            "@@ -0,0 +1 @@\n+t\n")
        names = [n for n, _ in core.split_patch_sections(patch)]
        self.assertEqual(names, ["tab\tname.py", 'q"uote.py'])

    def test_bare_spaced_path_symmetric_header(self):
        patch = ("diff --git a/my file.py b/my file.py\n"
                 "--- a/my file.py\n+++ b/my file.py\n"
                 "@@ -0,0 +1 @@\n+s\n")
        self.assertEqual(
            [n for n, _ in core.split_patch_sections(patch)],
            ["my file.py"])

    def test_added_lines_and_stats_use_real_path(self):
        q = _quoted("a/" + UNICODE_PATH)
        qb = _quoted("b/" + UNICODE_PATH)
        patch = (f"diff --git {q} {qb}\n--- {q}\n+++ {qb}\n"
                 "@@ -0,0 +1 @@\n+x = 1\n")
        self.assertEqual(
            [f for f, _n, _t in core.added_lines(patch)],
            [UNICODE_PATH])
        self.assertEqual(core._patch_stats(patch),
                         {UNICODE_PATH: [1, 0]})

    def test_rename_and_delete_still_resolve(self):
        patch = (
            "diff --git a/old.py b/new.py\n"
            "rename from old.py\nrename to new.py\n"
            "diff --git a/gone.py b/gone.py\n"
            "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n")
        self.assertEqual(
            [n for n, _ in core.split_patch_sections(patch)],
            ["new.py", "gone.py"])

    def test_real_git_unicode_path(self):
        """Her repro, end to end: a committed non-ASCII path
        is recorded under its real name, not 'unknown'."""
        with tempfile.TemporaryDirectory() as repo:
            env = dict(os.environ,
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t")

            def git(*args):
                subprocess.run(["git", "-C", repo, *args],
                               check=True, env=env,
                               capture_output=True)

            git("init", "-q")
            full = os.path.join(repo, UNICODE_PATH)
            os.makedirs(os.path.dirname(full))
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            git("add", "-A")
            git("commit", "-qm", "one")
            with open(full, "a", encoding="utf-8") as fh:
                fh.write("y = 2\n")
            patch = core.collect_git_patch(repo)
            self.assertIn(UNICODE_PATH,
                          [n for n, _ in
                           core.split_patch_sections(patch)])


class TestP602SameSecondStems(unittest.TestCase):
    """P6-02: two runs in one second to one --out shared a
    filename stem and the second silently overwrote the first
    — record loss. Auto stems now gain a counter suffix when
    taken; explicit stems (the hooks rewrite contract) are
    never renamed."""

    def setUp(self):
        self._real_datetime = core.datetime

        class FrozenDateTime:
            @staticmethod
            def now(tz=None):
                return _dt.datetime(2026, 11, 6, 12, 0, 0,
                                    tzinfo=tz)

        core.datetime = types.SimpleNamespace(
            datetime=FrozenDateTime, timezone=_dt.timezone,
            timedelta=_dt.timedelta)

    def tearDown(self):
        core.datetime = self._real_datetime

    @staticmethod
    def _report(marker):
        return {"gate": "blocked",
                "gate_reasons": [marker], "findings": []}

    def test_two_runs_same_second_both_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            j1, _ = core.write_report(self._report("first"), tmp)
            j2, _ = core.write_report(self._report("second"),
                                      tmp)
            self.assertNotEqual(j1, j2)
            self.assertTrue(j1.endswith(
                "codereview-20261106-120000.json"))
            self.assertTrue(j2.endswith(
                "codereview-20261106-120000-2.json"))
            with open(j1, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["gate_reasons"],
                                 ["first"])
            with open(j2, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["gate_reasons"],
                                 ["second"])

    def test_explicit_stem_still_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            core.write_report(self._report("first"), tmp,
                              stem="rec")
            jpath, _ = core.write_report(self._report("second"),
                                         tmp, stem="rec")
            self.assertEqual(os.path.basename(jpath), "rec.json")
            with open(jpath, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["gate_reasons"],
                                 ["second"])


class TestP610SortedKeys(unittest.TestCase):
    """P6-10: the written record's keys are sorted (the plan
    expects sorted top-level keys; serialisation sorts every
    level, which no consumer depends on being otherwise)."""

    def test_written_record_keys_sorted(self):
        report = {"version": "0", "gate": "pass",
                  "gate_reasons": [], "findings": [],
                  "mode": "review", "created_at": "2026-11-06",
                  "aardvark": 1, "zebra": 2}
        with tempfile.TemporaryDirectory() as tmp:
            jpath, _ = core.write_report(report, tmp,
                                         stem="rec")
            with open(jpath, encoding="utf-8") as fh:
                text = fh.read()
        pairs = json.loads(text, object_pairs_hook=lambda p: p)
        keys = [k for k, _v in pairs]
        self.assertEqual(keys, sorted(keys))


_PATCH = ("diff --git a/a.py b/a.py\n"
          "--- a/a.py\n"
          "+++ b/a.py\n"
          "@@ -1 +1 @@\n"
          "-x=1\n"
          "+x=2\n")


def _seat_ok(_prompt):
    return json.dumps({"summary": "ok", "findings": []})


def _seat_bad(_prompt):
    return json.dumps({
        "summary": "bad",
        "findings": [{
            "severity": "major", "category": "correctness",
            "file": "a.py", "line": 1, "title": "bug",
            "evidence": "x=2", "recommendation": "fix"}]})


def _written_record(tmp):
    report = core.run_review(
        _PATCH, {"alpha": _seat_bad, "beta": _seat_ok})
    jpath, _mpath = core.write_report(report, tmp)
    with open(jpath, encoding="utf-8") as fh:
        return json.load(fh)


def _named(result, name):
    for check in result["checks"]:
        if check["name"] == name:
            return check
    raise AssertionError(f"no check named {name}")


class TestP603ContentIntegrity(unittest.TestCase):
    """P6-03: record-verify accepted hand-edited records —
    record_identity.id covers four fields and was never
    recomputed. The writer now stamps a content hash over the
    whole record (minus the identity envelope); verify
    recomputes it in single and chain mode. Legacy records
    (no hash) verify as not-applicable, never retro-failed.

    P6-12 (rerun): the legacy reading was unbounded — deleting
    the hash from a CURRENT record made any edit invisible.
    The exemption now applies only when the record's own
    provenance declarations (generator version, created_at)
    predate the stamp; a stamping-era record without its
    hash fails. The pre-P6-12 pin asserted the stripped
    current record passed as legacy — that pin enshrined
    the defect and is replaced by the stripped-hash pins
    below; the genuine legacy cases (golden fixture,
    pre-stamp provenance) keep their pins.

    P6-12 (rerun 2): the bound still failed open — it
    trusted any ONE declaration and read missing or
    unparseable fields as pre-stamp, so stripping the
    hash plus deleting or garbling two fields passed an
    edited record as legacy (her p6_downgrade2.py, seven
    variants). The rule now fails closed: all three
    declarations (version, provenance.generator_version,
    created_at) are read; a stamping-era or unparseable
    declaration defeats the exemption, and so does having
    no usable declarations at all. The rerun-1
    pre-stamp pin modelled its "legacy" cases by editing
    ONE field of a current record — the fail-open shape
    itself — so those two sub-cases are replaced by
    consistent-provenance cases (every declaration
    pre-stamp) plus a pin for the documented cost: a
    0.13.0-line record created before the stamp landed
    (the dev-build window) no longer reads as legacy.

    P6-12b (rerun 3): the pre-machinery scope boundary
    was categorical — deleting the three machinery
    sections (`schema_version`, `provenance`,
    `record_identity`) skipped the declarations rule
    entirely, so a current record stripped of them read
    legacy even while still declaring
    `version: 0.13.0.dev0` (her p6_downgrade3.py G6),
    and deleting all five declarations read legacy on
    no evidence at all (her G1). The rule now applies
    inside the pre-machinery shape: the surviving
    declarations are read by the same fail-closed rule.
    The rerun-2 boundary pin asserted the all-five-
    deleted shape read legacy — that shape IS G1, so
    the pin enshrined the defect and is replaced below
    by the G1/G6 failure pins plus a pin for the genuine
    pre-schema shape (no machinery sections, but a
    pre-stamp `version` and `created_at` — what every
    writer of that era actually stamped), which stays
    legacy. Her G2/G3/G4 (forge every declaration
    consistently pre-stamp) stay rc 0: the documented
    not-a-signature limit, unchanged."""

    def test_written_record_carries_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        self.assertIn("content_sha256",
                      record["record_identity"])
        result = core.verify_record(record)
        check = _named(result, "content_integrity")
        self.assertTrue(check["ok"], check)

    def test_finding_edit_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["findings"][0]["title"] = "edited by hand"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_forged_test_results_fail_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["test_results"] = [
            {"command": "make test", "ok": True}]
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_gate_edit_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["gate"] = "pass"
        record["verdict"] = "PASS"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_stripped_hash_on_current_record_fails(self):
        # P6-12, her p6_downgrade case (1): delete the hash
        # from a record the current writer just stamped.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]["content_sha256"]
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)
        self.assertIn("removed", check["detail"])

    def test_stripped_hash_with_edit_fails(self):
        # P6-12, her case (2): delete the hash AND edit —
        # the downgrade that made tampering invisible.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]["content_sha256"]
        record["reviewer_reports"][0]["family"] = "anthropic"
        record["findings"].append({
            "severity": "nit", "title": "planted",
            "file": "a.py", "line": 1})
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_stripped_whole_identity_on_current_record_fails(
            self):
        # P6-12, her case (3): delete the whole envelope.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_prestamp_provenance_record_is_legacy(self):
        # The bounded exemption, rerun-2 shape: legacy
        # needs positive, CONSISTENT pre-stamp evidence —
        # every declaration the record carries predates
        # the stamp. Case 1 is the golden-fixture shape
        # (0.12.1 generator, created before the stamp
        # landed, provenance in agreement). Case 2 is the
        # sparse historical shape (0.9.x, no provenance
        # section at all, created 2026-11-04).
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]["content_sha256"]
        record["version"] = "0.12.1"
        record["provenance"]["generator_version"] = "0.12.1"
        record["created_at"] = "2026-11-06T05:00:42+00:00"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertTrue(check["ok"], check)
        self.assertIn("legacy", check["detail"])
        with tempfile.TemporaryDirectory() as tmp:
            sparse = _written_record(tmp)
        del sparse["record_identity"]["content_sha256"]
        sparse["version"] = "0.9.6"
        del sparse["provenance"]
        sparse["created_at"] = "2026-11-04T23:32:59+00:00"
        check = _named(core.verify_record(sparse),
                       "content_integrity")
        self.assertTrue(check["ok"], check)
        self.assertIn("legacy", check["detail"])

    def test_dev_window_record_no_longer_reads_legacy(self):
        # The documented rerun-2 cost, pinned deliberately:
        # a 0.13.0-line record created BEFORE the stamp
        # landed (the unstamped dev-build window) carries
        # stamping-era version declarations, so a missing
        # hash now fails closed instead of reading legacy
        # on created_at alone.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]["content_sha256"]
        record["created_at"] = "2026-11-06T20:00:00+00:00"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def _downgrade_variant(self, mutate):
        """A just-written record with its hash stripped,
        a planted finding appended, and `mutate` applied
        to its provenance — her p6_downgrade2.py shapes."""
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["record_identity"].pop("content_sha256", None)
        record["findings"].append({
            "severity": "blocker", "title": "hidden",
            "file": "app.py", "line": 1})
        mutate(record)
        return _named(core.verify_record(record),
                      "content_integrity")

    def test_downgrade2_forged_version_fails(self):
        check = self._downgrade_variant(
            lambda r: r.update(version="0.12.1"))
        self.assertFalse(check["ok"], check)

    def test_downgrade2_forged_created_at_fails(self):
        check = self._downgrade_variant(
            lambda r: r.update(
                created_at="2026-11-01T00:00:00+00:00"))
        self.assertFalse(check["ok"], check)

    def test_downgrade2_forged_both_fields_fails(self):
        check = self._downgrade_variant(
            lambda r: r.update(
                version="0.12.1",
                created_at="2026-10-01T00:00:00+00:00"))
        self.assertFalse(check["ok"], check)

    def test_downgrade2_deleted_provenance_fields_fail(self):
        def mutate(r):
            r.pop("version", None)
            r.pop("created_at", None)
        check = self._downgrade_variant(mutate)
        self.assertFalse(check["ok"], check)

    def test_downgrade2_garbled_version_fails(self):
        check = self._downgrade_variant(
            lambda r: r.update(version="garbage"))
        self.assertFalse(check["ok"], check)

    def test_downgrade2_garbled_created_at_fails(self):
        check = self._downgrade_variant(
            lambda r: r.update(created_at="not-a-date"))
        self.assertFalse(check["ok"], check)

    def test_downgrade2_deleted_identity_old_version_fails(
            self):
        def mutate(r):
            r.pop("record_identity", None)
            r.update(version="0.9.0")
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["findings"].append({
            "severity": "blocker", "title": "hidden",
            "file": "app.py", "line": 1})
        mutate(record)
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_downgrade2_no_provenance_at_all_fails(self):
        def mutate(r):
            r.pop("version", None)
            r.pop("created_at", None)
            r.pop("provenance", None)
        check = self._downgrade_variant(mutate)
        self.assertFalse(check["ok"], check)

    def test_pre_machinery_current_version_fails(self):
        # P6-12b, her G6: delete the three machinery
        # sections from a current record but KEEP
        # `version: 0.13.0.dev0`. A record that declares
        # the current version cannot be a pre-machinery
        # record — the surviving declaration is read and
        # defeats the exemption.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        for key in ("schema_version", "provenance",
                    "record_identity"):
            record.pop(key, None)
        record["findings"].append({
            "severity": "blocker", "title": "hidden",
            "file": "app.py", "line": 1})
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_pre_machinery_no_declarations_fails(self):
        # P6-12b, her G1: delete the machinery sections
        # AND both remaining declarations. The record
        # declares nothing, so nothing establishes a
        # pre-stamp legacy record — absent provenance is
        # not pre-stamp provenance. (This replaces the
        # rerun-2 boundary pin, which asserted this exact
        # shape read legacy; see the class docstring.)
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        for key in ("schema_version", "provenance",
                    "record_identity", "version",
                    "created_at"):
            record.pop(key, None)
        record["findings"].append({
            "severity": "blocker", "title": "hidden",
            "file": "app.py", "line": 1})
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertFalse(check["ok"], check)

    def test_pre_machinery_genuine_record_is_legacy(self):
        # The surviving boundary: a record with NO
        # machinery sections but the declarations every
        # writer of the pre-schema era actually stamped
        # (pre-stamp `version` + `created_at` — the
        # 0.9.4 / 0.9.6 historical shape) still reads
        # legacy on that positive evidence.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        for key in ("schema_version", "provenance",
                    "record_identity"):
            record.pop(key, None)
        record["version"] = "0.9.6"
        record["created_at"] = "2026-11-04T23:32:59+00:00"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertTrue(check["ok"], check)
        self.assertIn("legacy", check["detail"])

    def test_chain_mode_forged_provenance_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _written_record(tmp)
            r2 = _written_record(tmp)
        del r2["record_identity"]["content_sha256"]
        r2["version"] = "garbage"
        bad = _named(core.verify_chain([r1, r2]),
                     "content_integrity")
        self.assertFalse(bad["ok"], bad)

    def test_chain_mode_stripped_hash_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _written_record(tmp)
            r2 = _written_record(tmp)
        del r2["record_identity"]["content_sha256"]
        bad = _named(core.verify_chain([r1, r2]),
                     "content_integrity")
        self.assertFalse(bad["ok"], bad)

    def test_golden_fixture_records_are_legacy(self):
        fixtures = os.path.join(os.path.dirname(__file__),
                                "fixtures", "record_schema")
        with open(os.path.join(fixtures, "blocked.json"),
                  encoding="utf-8") as fh:
            record = json.load(fh)
        self.assertNotIn("content_sha256",
                         record["record_identity"])
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertTrue(check["ok"], check)

    def test_chain_mode_detects_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _written_record(tmp)
            r2 = _written_record(tmp)
        ok = _named(core.verify_chain([r1, r2]),
                    "content_integrity")
        self.assertTrue(ok["ok"], ok)
        r2["findings"][0]["title"] = "edited by hand"
        bad = _named(core.verify_chain([r1, r2]),
                     "content_integrity")
        self.assertFalse(bad["ok"], bad)

    def test_renamed_file_still_verifies(self):
        # The hash excludes the identity envelope, so the
        # recorded path (location metadata) is not content:
        # a record travelling under a new file name verifies.
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        record["record_identity"]["path"] = "renamed.json"
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertTrue(check["ok"], check)


class TestP605EscalatedInInventory(unittest.TestCase):
    """P6-05 (her j8b/j8c): while the Tech Lead escalates a
    finding to the owner and the gate sits INCONCLUSIVE, the
    finding was absent from the disputes inventory and
    `disputes --check` exited 0. Escalated is a human-decision
    state: it belongs in the inventory until the owner rules
    (a disposition entry closes it, like any dispute)."""

    FID = "610401f91b1c"

    def _drop_record(self, root):
        record = {
            "schema": "codereview.report/1", "mode": "review",
            "gate": "inconclusive", "head": "abc123",
            "range": "a..b", "findings": [],
            "escalated_findings": [{
                "id": self.FID, "severity": "blocker",
                "category": "correctness", "file": "app.py",
                "line": 2, "title": "cwd leak",
                "status": "escalated",
                "sources": ["alpha"],
                "adjudication": {
                    "decision": "escalate",
                    "escalation_reason": "protected class"}}],
            "reviewer_reports": [{
                "provider": "alpha", "lens": "correctness",
                "status": "ok", "family": "famA",
                "findings": [{"id": self.FID}]}]}
        rdir = os.path.join(root, "review-t1")
        os.makedirs(rdir)
        with open(os.path.join(rdir, "rec.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(record, fh)

    def test_escalated_finding_is_inventoried(self):
        from codereview import disputes
        with tempfile.TemporaryDirectory() as tmp:
            self._drop_record(tmp)
            inv = disputes.build_inventory(tmp, [])
        self.assertEqual([r["id"] for r in inv["open"]],
                         [self.FID])
        row = inv["open"][0]
        self.assertEqual(row["status"], "escalated")
        self.assertEqual(row["escalation_reason"],
                         "protected class")

    def test_owner_disposition_closes_the_escalation(self):
        from codereview import disputes
        entry = {"finding_id": self.FID,
                 "type": "sustain_finding", "decider": "owner",
                 "date": "2026-11-06T12:00:00+00:00"}
        with tempfile.TemporaryDirectory() as tmp:
            self._drop_record(tmp)
            inv = disputes.build_inventory(tmp, [entry])
        self.assertEqual(inv["open"], [])
        self.assertEqual(
            [r["id"] for r in inv["dispositioned"]], [self.FID])


class TestP606AgentFamilies(unittest.TestCase):
    """P6-06 (her j4/j4b): agent-CLI seats were all family
    'agent', so a Claude+Codex panel computed as a single
    family — 'no independent review', and two_families
    release eligibility was impossible without a hand-written
    --seat-meta that setup never saved. Family now derives
    from the CLI the seat runs, and setup persists the seat
    metadata it derives."""

    def test_describe_spec_derives_vendor_family(self):
        from codereview import providers
        cases = [
            ("agent:claude:claude -p x", "anthropic"),
            ("agent:codex:codex exec", "openai"),
            ("agent:gemini:gemini -p x", "google"),
            # the command's program decides, not the seat name
            ("agent:reviewer:codex exec", "openai"),
            # a seat NAMED for a known CLI but running
            # something else is NOT that vendor (review-v11)
            ("agent:gemini:echo hi", "agent"),
            ("agent:claude:/opt/bin/wrapper.sh", "agent"),
            # an unknown CLI keeps the generic family
            ("agent:bot:mytool run", "agent"),
        ]
        for spec, family in cases:
            self.assertEqual(
                providers.describe_spec(spec)["family"],
                family, spec)

    def test_two_agent_vendors_two_families_end_to_end(self):
        from codereview import cli, providers
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("claude", "codex"):
                path = os.path.join(tmp, name)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(
                        "#!/usr/bin/env python3\n"
                        "import sys, json\n"
                        "sys.stdin.read()\n"
                        "sys.stdout.write(json.dumps("
                        "{'summary': 'ok', 'findings': []}))\n")
                os.chmod(path, 0o755)
            specs = [f"agent:claude:{tmp}/claude",
                     f"agent:codex:{tmp}/codex"]
            panel = providers.build_providers(specs)
            meta = cli._default_seat_meta(panel)
            self.assertEqual(
                {m["family"] for m in meta.values()},
                {"anthropic", "openai"})
            report = core.run_review(_PATCH, panel,
                                     seat_meta=meta)
            self.assertEqual(report["gate"], "pass")
            self.assertNotIn(
                "no independent review",
                " ".join(report["gate_reasons"]))
            check = _named(core.verify_record(report),
                           "two_families")
            self.assertTrue(check["ok"], check)

    def test_userconfig_seat_meta_round_trip(self):
        from codereview import userconfig
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"HOME": tmp,
                       "CODEREVIEW_CONFIG":
                           os.path.join(tmp, "config.toml")}
            userconfig.save_user_config(
                ["agent:claude:claude -p x"], {},
                environ=environ,
                seat_meta={"claude": "anthropic"})
            self.assertEqual(
                userconfig.default_seat_meta(environ),
                {"claude": "anthropic"})
            with open(environ["CODEREVIEW_CONFIG"],
                      encoding="utf-8") as fh:
                self.assertIn("[seat_meta]", fh.read())

    def test_wizard_persists_derived_seat_meta(self):
        from codereview import setup_wizard, userconfig
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"HOME": tmp, "PATH": "",
                       "CODEREVIEW_CONFIG":
                           os.path.join(tmp, "config.toml")}
            answers = iter([
                "agent:claude:claude -p x",  # providers
                "",                           # family guard
                "", "", "", "", "",           # roles
            ])
            result = setup_wizard.run_wizard(
                input_fn=lambda _p: next(answers),
                print_fn=lambda _s: None, environ=environ,
                discover_fn=lambda: [])
            self.assertEqual(result["seat_meta"],
                             {"claude": "anthropic"})
            self.assertEqual(
                userconfig.default_seat_meta(environ),
                {"claude": "anthropic"})


class TestP607RegroundCap(unittest.TestCase):
    """P6-07 (her n_scale2): the re-ground pass made one model
    call per ungrounded finding with no cap — 3,000 findings
    cost 2,996 calls. The pass now has a call budget
    (core.MAX_REGROUND_CALLS); findings past it stay
    ungrounded with the budget named, never silently."""

    def test_fanout_is_capped_and_the_record_says_so(self):
        calls = {"n": 0}
        findings = [{
            "severity": "major", "category": "correctness",
            "file": "a.py", "line": i + 1,
            "title": f"tok{i}x tok{i}y tok{i}z",
            "evidence": f"a quote {i} that is not in the diff",
            "recommendation": "fix"} for i in range(80)]

        def seat(_prompt):
            calls["n"] += 1
            return json.dumps({"summary": "s",
                               "findings": findings})

        meta = {"alpha": {"family": "google", "tier": "paid"},
                "beta": {"family": "openai", "tier": "paid"}}
        report = core.run_review(
            _PATCH, {"alpha": seat, "beta": seat},
            seat_meta=meta)
        reground_calls = calls["n"] - 2  # two review batches
        self.assertGreater(reground_calls, 0)
        self.assertLessEqual(reground_calls,
                             core.MAX_REGROUND_CALLS)
        capped = [f for f in report["findings"]
                  if "call budget" in
                  (f.get("reground_note") or "")]
        self.assertTrue(capped)
        self.assertTrue(any(
            "call budget" in r
            for r in report["gate_reasons"]))


class TestP609OnSeatBlockedAlias(unittest.TestCase):
    """P6-09: `on_blocked` fires when a SEAT blocks (K2 class),
    not when the gate verdict is BLOCKED — the name invited
    the misreading. The event keeps its name (no breaking
    rename); the policy key gains the additive alias
    `on_seat_blocked`, folded into the same slot at load."""

    def _load(self, tmp, hooks_toml):
        from codereview import policy
        path = os.path.join(tmp, ".codereview.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(hooks_toml)
        return policy.load_policy(path)

    def test_alias_fills_the_on_blocked_slot(self):
        from codereview import hooks
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._load(
                tmp, '[hooks]\non_seat_blocked = "echo hi"\n')
        self.assertEqual(pol["hooks"]["on_blocked"], "echo hi")
        config = hooks.hooks_from_policy(pol)
        self.assertEqual(config["on_blocked"], "echo hi")

    def test_canonical_key_wins_over_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = self._load(
                tmp, '[hooks]\non_blocked = "echo canon"\n'
                     'on_seat_blocked = "echo alias"\n')
        self.assertEqual(pol["hooks"]["on_blocked"],
                         "echo canon")


if __name__ == "__main__":
    unittest.main()
