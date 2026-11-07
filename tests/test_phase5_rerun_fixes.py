"""Phase 5 RERUN (on ebfa217) regression pins. One class per
rerun finding; each test names the behaviour the rerun found
missing and that master must now hold. P5-08b's pins live in
tests/test_claim_lint.py (the lint is that file); P5-14 was
checked against the launcher source and is NOT a defect —
the string there is intact (see TestP514LauncherWording)."""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli as _cli  # noqa: E402
from codereview import core  # noqa: E402
from codereview import github  # noqa: E402
from codereview import sarif  # noqa: E402

DIFF = ("diff --git a/app.py b/app.py\n"
        "--- a/app.py\n+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n x = 1\n+run_all_the_things()\n")


def _ok_reviewer(prompt):
    return json.dumps({"findings": [], "summary": "s", "usage": {}})


class TestP507bProbeProvesWritability(unittest.TestCase):
    """P5-07b (1): the up-front --out check must PROVE
    writability with a real create. os.access passes for root
    on /proc and /sys (the rerun's repro); the probe fails
    there for every user."""

    def test_probe_catches_what_a_lying_access_passes(self):
        with mock.patch("os.access", return_value=True):
            self.assertIsNotNone(_cli._out_dir_problem("/proc/nope"))
            self.assertIsNotNone(_cli._out_dir_problem("/sys/nope"))

    def test_probe_cleans_up_after_itself(self):
        tmp = tempfile.mkdtemp()
        nested = os.path.join(tmp, "new", "nested")
        self.assertIsNone(_cli._out_dir_problem(nested))
        # The directories the probe created are removed again,
        # and no probe file is left in an existing directory.
        self.assertFalse(os.path.exists(nested))
        self.assertIsNone(_cli._out_dir_problem(tmp))
        self.assertEqual(os.listdir(tmp), [])


class TestP507bWriteFailureKeepsTheReview(unittest.TestCase):
    """P5-07b (2): a late write_report OSError (disk full,
    mount gone read-only mid-run) must not discard the
    completed review: verdict on stdout, record in a fallback
    location, exit 2 — no traceback."""

    def test_write_report_helper_falls_back(self):
        tmp = tempfile.mkdtemp()
        workdir = os.path.join(tmp, "cwd")
        os.makedirs(workdir)
        target = os.path.join(tmp, "out")
        real_write = core.write_report

        def selective(report, out_dir, stem=None):
            if out_dir == target:
                raise OSError(28, "No space left on device")
            return real_write(report, out_dir, stem=stem)

        report = {"gate": "blocked",
                  "gate_reasons": ["seat blocked: auth"],
                  "findings": []}
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(workdir)
        try:
            with mock.patch.object(core, "write_report",
                                   side_effect=selective), \
                    mock.patch("sys.stdout", out):
                with self.assertRaises(_cli._ReportWriteFailed):
                    _cli._write_report(report, target, "codereview")
        finally:
            os.chdir(old)
        self.assertIn("gate = BLOCKED", out.getvalue())
        records = [f for f in os.listdir(workdir)
                   if f.endswith(".json")]
        self.assertEqual(len(records), 1)
        with open(os.path.join(workdir, records[0])) as fh:
            self.assertEqual(json.load(fh)["gate"], "blocked")

    def test_main_write_failure_exits_2_with_verdict(self):
        calls = []

        def counting(prompt):
            calls.append(1)
            return _ok_reviewer(prompt)

        tmp = tempfile.mkdtemp()
        patch = os.path.join(tmp, "p.diff")
        with open(patch, "w") as fh:
            fh.write(DIFF)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(
                core, "write_report",
                side_effect=OSError(28, "No space left")), \
                mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", err):
            rc = _cli.main(
                ["--patch", patch, "--out", os.path.join(tmp, "o")],
                providers_override={"fake": counting})
        self.assertEqual(rc, 2)
        self.assertTrue(calls)  # the review DID complete
        self.assertIn("gate = PASS", out.getvalue())
        # Last-resort preservation: the record itself is on
        # stdout when no location is writable.
        self.assertIn('"gate": "pass"', out.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


class TestP504bReasonsLineNeutralised(unittest.TestCase):
    """P5-04b: gate_reasons can carry untrusted (repo-policy-)
    derived text; the rendered reasons line must carry no
    live autolink, cross-reference or reference-style link."""

    def test_reasons_line_has_no_live_forms(self):
        report = {
            "gate": "pass",
            "gate_reasons": [
                "see https://evil.example/login and #1234 and "
                "octo/repo#9 [click][r]\n\n"
                "[r]: https://evil.example"],
            "findings": [], "version": "0",
            "patch_sha256": "x" * 32}
        md = github.render_pr_comment(report, "o", "r", 7)
        self.assertNotIn("https://", md)          # autolink dead
        self.assertNotIn("#1234", md)             # cross-ref dead
        self.assertNotIn("#9", md.replace("PR #7", ""))
        self.assertNotIn("[click][r]", md)        # ref link split
        self.assertIsNone(                        # no live def
            re.search(r"(?m)^\[r\]:", md))


class TestP501bSarifDotDotResolves(unittest.TestCase):
    """P5-01b: `..` resolves via normpath; a path that still
    escapes the root gets no location instead of a pointer
    at the wrong file."""

    def _result(self, file):
        record = {"gate": "blocked", "findings": [
            {"id": "f1", "severity": "major", "title": "t",
             "category": "security", "file": file}]}
        log = sarif.record_to_sarif(record)
        return log["runs"][0]["results"][0]

    def test_escaping_paths_omit_the_location(self):
        for hostile in ("a/../../b.py", "../../etc/passwd"):
            self.assertNotIn("locations", self._result(hostile),
                             hostile)

    def test_inner_dotdot_resolves(self):
        result = self._result("a/b/../c.py")
        uri = result["locations"][0]["physicalLocation"][
            "artifactLocation"]["uri"]
        self.assertEqual(uri, "a/c.py")


class TestP514LauncherWording(unittest.TestCase):
    """P5-14 rerun note: the tester's capture showed the
    launcher's file-path message clipped ('pace path is not
    a directory'). Checked against the source: NOT a defect —
    the literal is intact; her harness clipped the line.
    Pinned here so the wording cannot silently regress."""

    def test_launcher_messages_are_intact(self):
        path = os.path.join(
            os.path.dirname(__file__), "..",
            "herdr-plugin-codereview", "codereview_launch.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("workspace path is not a ", src)
        self.assertIn("directory: {repo}", src)
        self.assertIn("workspace directory does not ", src)
        self.assertIn("exist: {repo}", src)


if __name__ == "__main__":
    unittest.main()
