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
    (no hash) verify as not-applicable, never retro-failed."""

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

    def test_legacy_record_is_not_applicable_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = _written_record(tmp)
        del record["record_identity"]["content_sha256"]
        check = _named(core.verify_record(record),
                       "content_integrity")
        self.assertTrue(check["ok"], check)
        self.assertIn("legacy", check["detail"])

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


if __name__ == "__main__":
    unittest.main()
