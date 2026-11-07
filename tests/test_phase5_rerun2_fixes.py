"""Phase 5 SECOND-rerun (on 784ff95) regression pins.

The rerun verified all four previous residuals fixed and
raised two S3s in the claim lint — P5-08c/P5-08d, whose pins
live in tests/test_claim_lint.py (the lint is that file).
This file pins the remaining item, the P6-01 remainder: the
P5-07b fallback net caught a midway write failure, but
core.write_report still wrote the final path IN PLACE, so a
file-size limit (or disk full, or a kill) left a truncated,
invalid JSON record at the final path for any tool scanning
--out to pick up. The hooks' rewrite of the record (the CLI
writes the record, fires the post-record hooks, then
rewrites it at the same stem with the completed hooks
ledger) went through the same in-place write, where a torn
rewrite would destroy the complete record the hooks were
handed. write_report now writes both files atomically:
temp file in the same directory, fsync, os.replace; on
failure the temp is removed and the previous file (or
nothing) stands at the final path.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli as _cli  # noqa: E402
from codereview import core  # noqa: E402

SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src"))

# The RLIMIT_FSIZE repro runs in a child: a file-size limit
# is process state the test process must not carry. The
# child reports a caught OSError as exit 3 + "OSERROR".
CHILD = r"""
import json, os, resource, sys
sys.path.insert(0, os.environ["CR_SRC"])
from codereview import core
scenario, out = sys.argv[1], sys.argv[2]
if scenario == "md":
    # A small record (its JSON fits the limit easily) whose
    # MARKDOWN does not: the .md write is the one that fails
    # midway.
    core.render_markdown = lambda rec: "x" * 100000
    resource.setrlimit(resource.RLIMIT_FSIZE, (8000, 8000))
    report = {"gate": "pass", "gate_reasons": [], "findings": []}
else:
    resource.setrlimit(resource.RLIMIT_FSIZE, (2000, 2000))
    report = {"gate": "blocked", "gate_reasons": ["r" * 500],
              "findings": [{"severity": "major",
                            "summary": "s" * 4000}]}
try:
    core.write_report(report, out, stem="rec")
except OSError as exc:
    print("OSERROR", exc.errno)
    sys.exit(3)
print("WROTE")
"""


def _run_child(scenario, out_dir):
    tmp = tempfile.mkdtemp()
    script = os.path.join(tmp, "child.py")
    with open(script, "w") as fh:
        fh.write(CHILD)
    env = dict(os.environ, CR_SRC=SRC)
    proc = subprocess.run(
        [sys.executable, script, scenario, out_dir],
        capture_output=True, text=True, env=env)
    return proc


def _ok_reviewer(prompt):
    return json.dumps({"findings": [], "summary": "s", "usage": {}})


class TestP601AtomicWriteReport(unittest.TestCase):
    """P6-01: a midway write failure leaves a complete file
    or nothing at the final path — never a truncated one."""

    def test_happy_path_leaves_no_temp_files(self):
        tmp = tempfile.mkdtemp()
        report = {"gate": "pass", "gate_reasons": [],
                  "findings": []}
        jpath, mpath = core.write_report(report, tmp, stem="rec")
        self.assertEqual(sorted(os.listdir(tmp)),
                         ["rec.json", "rec.md"])
        with open(jpath) as fh:
            self.assertEqual(json.load(fh)["gate"], "pass")
        self.assertTrue(os.path.getsize(mpath) > 0)

    def test_rlimit_failure_on_fresh_write_leaves_nothing(self):
        tmp = tempfile.mkdtemp()
        proc = _run_child("fresh", tmp)
        self.assertEqual(proc.returncode, 3, proc.stdout)
        self.assertIn("OSERROR", proc.stdout)
        # No truncated record, no .md, no temp leftovers.
        self.assertEqual(os.listdir(tmp), [])

    def test_rlimit_failure_on_rewrite_preserves_the_record(self):
        # The hooks-rewrite shape: a complete record already
        # stands at the final path and the rewrite fails
        # midway. The previous record must survive byte for
        # byte — before the fix it was truncated in place.
        tmp = tempfile.mkdtemp()
        good = {"gate": "pass", "gate_reasons": [],
                "findings": []}
        jpath, mpath = core.write_report(good, tmp, stem="rec")
        with open(jpath, "rb") as fh:
            json_before = fh.read()
        with open(mpath, "rb") as fh:
            md_before = fh.read()
        proc = _run_child("fresh", tmp)
        self.assertEqual(proc.returncode, 3, proc.stdout)
        with open(jpath, "rb") as fh:
            self.assertEqual(fh.read(), json_before)
        with open(mpath, "rb") as fh:
            self.assertEqual(fh.read(), md_before)
        self.assertEqual(sorted(os.listdir(tmp)),
                         ["rec.json", "rec.md"])

    def test_rlimit_failure_on_markdown_keeps_valid_json(self):
        tmp = tempfile.mkdtemp()
        proc = _run_child("md", tmp)
        self.assertEqual(proc.returncode, 3, proc.stdout)
        # The JSON landed complete (atomically) before the
        # .md write failed; the .md is absent, not truncated.
        self.assertEqual(os.listdir(tmp), ["rec.json"])
        with open(os.path.join(tmp, "rec.json")) as fh:
            self.assertEqual(json.load(fh)["gate"], "pass")


class TestP601HooksRewriteFailure(unittest.TestCase):
    """P6-01, the hooks' rewrite (the tester's regression
    shape): the record is written, the post-verdict hook
    fires, and the rewrite at the same stem fails midway.
    The first record must stand intact at the final path,
    the verdict is printed, and the run exits 2 via the
    P5-07b net (which saves the updated record to the
    fallback location)."""

    def test_rewrite_failure_keeps_first_record_exits_2(self):
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)

        def git(*a):
            subprocess.run(["git", *a], cwd=repo, check=True,
                           capture_output=True)

        git("init", "-q")
        git("config", "user.email", "a@b")
        git("config", "user.name", "t")
        with open(os.path.join(repo, "app.py"), "w") as fh:
            fh.write("import os\n")
        git("add", ".")
        git("commit", "-qm", "i")
        with open(os.path.join(repo, "app.py"), "w") as fh:
            fh.write("import os\nx = os.getcwd()\n")
        hook = os.path.join(tmp, "hook.sh")
        with open(hook, "w") as fh:
            fh.write('#!/bin/sh\necho hook-ran\n')
        os.chmod(hook, 0o755)
        pol = os.path.join(tmp, "pol.toml")
        with open(pol, "w") as fh:
            fh.write('[hooks]\npost_verdict = %s\n'
                     % json.dumps(hook))
        out = os.path.join(tmp, "out")
        # write_report replaces twice per call (json, md).
        # Fail the THIRD replace: the hooks rewrite's record.
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError(28, "No space left on device")
            return real_replace(src, dst)

        stdout = io.StringIO()
        old = os.getcwd()
        os.chdir(tmp)  # the fallback write lands here
        try:
            with mock.patch("os.replace",
                            side_effect=flaky_replace), \
                    mock.patch("sys.stdout", stdout), \
                    mock.patch("sys.stderr", io.StringIO()):
                rc = _cli.main(
                    ["--repo", repo, "--policy", pol,
                     "--out", out],
                    providers_override={"a": _ok_reviewer,
                                        "b": _ok_reviewer})
        finally:
            os.chdir(old)
        self.assertEqual(rc, 2)
        self.assertGreaterEqual(calls["n"], 4)  # fallback ran
        self.assertIn("gate = PASS", stdout.getvalue())
        # The first record stands intact at the final path.
        names = os.listdir(out)
        self.assertFalse(any(".tmp-" in n for n in names))
        jsons = [n for n in names if n.endswith(".json")]
        self.assertEqual(len(jsons), 1)
        with open(os.path.join(out, jsons[0])) as fh:
            record = json.load(fh)
        self.assertEqual(record["gate"], "pass")
        # And the P5-07b net preserved the updated record in
        # the fallback location (the working directory).
        self.assertTrue(any(f.endswith(".json")
                            for f in os.listdir(tmp)))


if __name__ == "__main__":
    unittest.main()
