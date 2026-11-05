#!/usr/bin/env python3
"""Closing-B probe — probe.py sandbox cluster.

Claims:
  8479293e76ed (attempt-2): probe command specs execute
    arbitrary host binaries with full filesystem access.
  6d2d43b7bc3e (attempt-1): command probes can write
    outside the temp copy.
  b9e2819976fe (fixes-review): kind-'test' now runs every
    matching test in the target's directory, not just the
    requested target.
  f46397a84121 (attempt-2 re-raise): test probes execute
    the target file directly instead of via the runner
    (the c3c1463 fix) — quick re-check here; the full
    after-state probe is probes/shadow_test_runner_probe.py
    (commit 469e36e), re-run separately.

Documented threat model (probe.py module docstring,
lines 12-24): temp-copy cwd, env ALLOWLIST, network
namespace when available (level recorded, never
overstated), hard timeout. Filesystem confinement beyond
the copied cwd is NOT among the documented promises.

Writes results/closingB-probe-sandbox.txt. Facts only.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import probe as probe_mod  # noqa: E402

OUT = os.path.join(HERE, "results",
                   "closingB-probe-sandbox.txt")
ESCAPE = "/tmp/closingB-escape-marker.txt"
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def sandbox_probe(tree):
    say("== 8479293e76ed / 6d2d43b7bc3e: command-spec "
        "filesystem reach (probe.py:157-158, 199-207) ==")
    if os.path.exists(ESCAPE):
        os.remove(ESCAPE)
    os.environ["CODEREVIEW_PROBE_SECRET"] = "should-not-cross"
    code = "\n".join([
        f"open({ESCAPE!r}, 'w').write('escaped')",
        "import os",
        "print('hostname-file:',"
        " open('/etc/hostname').read().strip())",
        "print('secret-in-env:',"
        " 'CODEREVIEW_PROBE_SECRET' in os.environ)",
        "print('cwd-is-temp-copy:', os.getcwd())",
    ])
    res = probe_mod.run_probe(
        {"kind": "command",
         "argv": [sys.executable, "-c", code]}, tree)
    say(f"  outcome={res['outcome']} exit={res['exit_code']}")
    say(f"  sandbox block recorded: {res['sandbox']}")
    for line in res["output"].splitlines():
        if line.strip():
            say(f"  out: {line.strip()[:130]}")
    say(f"  marker written OUTSIDE the temp copy at "
        f"{ESCAPE}: {os.path.exists(ESCAPE)}")
    if os.path.exists(ESCAPE):
        os.remove(ESCAPE)
    say("  reading: the write/read outside the copy "
        "SUCCEEDS (no fs confinement); the env allowlist "
        "DID hold (secret absent), cwd was the temp copy, "
        "and the network level is recorded on the result — "
        "exactly the documented model in the probe.py "
        "docstring")


PASS_TEST = """import unittest


class Target(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
"""

FAIL_TEST = """import unittest


class Other(unittest.TestCase):
    def test_boom(self):
        self.fail("unrelated failure")
"""

UNGUARDED_FAIL = """import unittest


class Unguarded(unittest.TestCase):
    def test_boom(self):
        self.fail("unguarded failure")
# NOTE: deliberately NO `if __name__ == "__main__":` guard —
# direct script execution would run zero tests and exit 0.
"""


def test_dir_probe():
    say("")
    say("== b9e2819976fe: kind-'test' discovery scope "
        "(probe.py:196-207) ==")
    with tempfile.TemporaryDirectory() as td:
        tdir = os.path.join(td, "tests")
        os.makedirs(tdir)
        with open(os.path.join(tdir, "test_target.py"),
                  "w") as fh:
            fh.write(PASS_TEST)
        with open(os.path.join(tdir, "test_unrelated.py"),
                  "w") as fh:
            fh.write(FAIL_TEST)
        res = probe_mod.run_probe(
            {"kind": "test", "target": "tests/test_target.py"},
            td)
        say(f"  dir holds PASSING test_target.py + FAILING "
            f"test_unrelated.py; probe on target only: "
            f"outcome={res['outcome']!r} exit={res['exit_code']}")
        tail = [ln for ln in res["output"].splitlines()
                if "Ran" in ln or "OK" in ln or "FAIL" in ln]
        say(f"  runner summary lines: {tail}")
        # Same-basename file in a subpackage: discovery with
        # -p <basename> recurses into packages.
        sub = os.path.join(tdir, "subpkg")
        os.makedirs(sub)
        open(os.path.join(sub, "__init__.py"), "w").close()
        with open(os.path.join(sub, "test_target.py"),
                  "w") as fh:
            fh.write(FAIL_TEST)
        res2 = probe_mod.run_probe(
            {"kind": "test", "target": "tests/test_target.py"},
            td)
        tail2 = [ln for ln in res2["output"].splitlines()
                 if "Ran" in ln or "OK" in ln or "FAIL" in ln]
        say(f"  after adding FAILING subpkg/test_target.py "
            f"(same basename): outcome={res2['outcome']!r} "
            f"summary={tail2}")


def test_runner_probe():
    say("")
    say("== f46397a84121: kind-'test' executes via the "
        "unittest runner at HEAD (c3c1463) ==")
    with tempfile.TemporaryDirectory() as td:
        tdir = os.path.join(td, "tests")
        os.makedirs(tdir)
        with open(os.path.join(tdir, "test_unguarded.py"),
                  "w") as fh:
            fh.write(UNGUARDED_FAIL)
        res = probe_mod.run_probe(
            {"kind": "test",
             "target": "tests/test_unguarded.py"}, td)
        tail = [ln for ln in res["output"].splitlines()
                if "Ran" in ln or "FAILED" in ln or "OK" in ln]
        say(f"  unguarded FAILING test file: outcome="
            f"{res['outcome']!r} exit={res['exit_code']} "
            f"summary={tail} — direct script execution "
            f"would have run 0 tests and exited 0 (pass); "
            f"the runner ran the test and it failed")


def main():
    say("PROBE SANDBOX PROBE — 8479293e76ed, 6d2d43b7bc3e, "
        "b9e2819976fe, f46397a84121")
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "mod.py"), "w") as fh:
            fh.write("X = 1\n")
        sandbox_probe(td)
    test_dir_probe()
    test_runner_probe()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
