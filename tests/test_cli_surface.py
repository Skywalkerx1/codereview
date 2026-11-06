"""CLI surface fixes from the external Phase 0–1 test report
(2026-11-06).

D-004: `codereview --version` exited 2 ("unrecognized
arguments"). Both console entry points (codereview and
reviewloop) are the same function, codereview.cli:main, so
--version is served by the top-level parser's version action
and prints core.VERSION.

D-005: `codereview policy --help`, `bench --help` and
`mcp --help` exited 2 with a bare usage line, because those
three two-level subcommands pre-checked argv[0] for their
action word before any ArgumentParser existed. They now build
a parser for the help case, like every other subcommand, so
--help prints real help and exits 0. Bare invocations
(`codereview policy` with no action) still exit 2.
"""

import contextlib
import io
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import cli, core  # noqa: E402

SUBCOMMANDS = (
    "setup", "doctor", "policy", "record-verify", "disputes",
    "bench", "intake", "pr", "workflow", "loop", "sarif",
    "evidence", "locate", "acceptance", "mcp")


def _exit_code(argv):
    """Run cli.main(argv) the way the --help tests do: argparse
    signals help/version by raising SystemExit."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                return exc.code, buf.getvalue()
    return code, buf.getvalue()


class VersionTests(unittest.TestCase):
    def test_version_flag_prints_core_version(self):
        code, out = _exit_code(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), core.VERSION)

    def test_version_via_module_entry_point(self):
        env = dict(os.environ)
        src = os.path.join(ROOT, "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get(
            "PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "codereview", "--version"],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), core.VERSION)


class SubcommandHelpTests(unittest.TestCase):
    def test_every_subcommand_help_exits_zero(self):
        for name in SUBCOMMANDS:
            with self.subTest(subcommand=name):
                code, out = _exit_code([name, "--help"])
                self.assertEqual(code, 0)
                self.assertIn("usage", out.lower())

    def test_two_level_subcommands_still_require_an_action(self):
        for name in ("policy", "bench", "mcp"):
            with self.subTest(subcommand=name):
                code, _out = _exit_code([name])
                self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
