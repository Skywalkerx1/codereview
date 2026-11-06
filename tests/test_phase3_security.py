"""Phase 3 (external security test pass) regression tests.

Each class pins one verified Phase 3 finding's fix. The
findings were reproduced against master 53f8987 before fixing;
these tests fail on the pre-fix code and pass after.
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "src"))

from codereview import cli, core  # noqa: E402

PASS_VERDICT = json.dumps({"verdict": "pass", "summary": "ok",
                           "findings": []})


def pass_provider(_prompt):
    return PASS_VERDICT


SIMPLE_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " x = 1\n"
    "+y = 2\n")


def run_cli(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv, **kw)
    return rc, out.getvalue(), err.getvalue()


def read_record(outdir):
    records = [f for f in os.listdir(outdir)
               if f.endswith(".json")]
    assert len(records) == 1, records
    with open(os.path.join(outdir, records[0]),
              encoding="utf-8") as fh:
        return json.load(fh)


class PolicyOriginObservabilityTests(unittest.TestCase):
    """P3-01 (observability half): a repo-discovered policy is
    applied as before, but the record states its origin, stderr
    warns, and a change that touches the gate's own config
    files is flagged on the record."""

    def _repo_with_policy(self, tmp):
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        with open(os.path.join(repo, ".codereview.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('[gate]\nprofile = "strict"\n')
        return repo

    def _patch_file(self, tmp, text=SIMPLE_PATCH):
        patch = os.path.join(tmp, "change.diff")
        with open(patch, "w", encoding="utf-8") as fh:
            fh.write(text)
        return patch

    def test_discovered_policy_records_origin_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo_with_policy(tmp)
            outdir = os.path.join(tmp, "out")
            rc, _out, err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "discovered-in-repo")
            self.assertIn("WARNING", err)
            self.assertIn("discovered in the reviewed "
                          "repository", err)

    def test_explicit_policy_records_explicit_origin_no_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            policy_path = os.path.join(tmp, "operator.toml")
            with open(policy_path, "w", encoding="utf-8") as fh:
                fh.write('[gate]\nprofile = "strict"\n')
            outdir = os.path.join(tmp, "out")
            rc, _out, err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--policy", policy_path,
                 "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(record["policy"]["origin"],
                             "explicit")
            self.assertNotIn("WARNING", err)

    def test_change_touching_policy_file_is_flagged(self):
        patch = (
            "diff --git a/.codereview.toml b/.codereview.toml\n"
            "--- a/.codereview.toml\n"
            "+++ b/.codereview.toml\n"
            "@@ -0,0 +1,1 @@\n"
            "+[gate]\n"
            "diff --git a/docs/AGENTS.md b/docs/AGENTS.md\n"
            "--- a/docs/AGENTS.md\n"
            "+++ b/docs/AGENTS.md\n"
            "@@ -0,0 +1,1 @@\n"
            "+# guidance\n")
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            outdir = os.path.join(tmp, "out")
            rc, _out, _err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp, patch), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertEqual(
                record["policy_self_modification"],
                [".codereview.toml", "docs/AGENTS.md"])

    def test_ordinary_change_has_no_self_modification_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(repo)
            outdir = os.path.join(tmp, "out")
            rc, _out, _err = run_cli(
                ["--repo", repo, "--patch",
                 self._patch_file(tmp), "--out", outdir],
                providers_override={"a": pass_provider})
            self.assertEqual(rc, 0)
            record = read_record(outdir)
            self.assertNotIn("policy_self_modification", record)
            self.assertNotIn("policy", record)


if __name__ == "__main__":
    unittest.main()
