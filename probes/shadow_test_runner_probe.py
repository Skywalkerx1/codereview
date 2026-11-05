#!/usr/bin/env python3
"""Test-probe runner probe — shadow-branch review, for
4cf81c69d7cf (refutation-weak): "Test probes are executed
as plain Python scripts instead of via the test runner."

Claim: probe.py's kind-"test" branch builds
argv = [sys.executable, spec["target"]] — the target FILE
is executed as a script; no test runner (unittest/pytest
discovery) is involved. The refutation calls direct
execution "the standard way to invoke a test file" and says
it "does not bypass the test runner".

Probe: two temp trees, each holding the SAME failing
unittest (assertEqual(1, 2)) at tests/test_demo.py:
  tree A — the file ends with the
    `if __name__ == "__main__": unittest.main()` guard;
  tree B — the identical test WITHOUT the guard.
For each: (1) run_probe({"kind": "test", "target":
"tests/test_demo.py"}, tree) — the harness's own verdict;
(2) the control: `python -m unittest discover` over the
same tree — the runner's verdict. Also record the repo's
own convention at HEAD: how many of tests/test_*.py carry
the guard, and name the one that does not (a kind-"test"
probe aimed at that file would import it, run zero tests,
and report pass).

Exit 0 = all four executions captured.

POST-FIX (shadow-fixes branch, after the owner ratified
sustain_finding): kind-"test" probes execute through the
unittest runner (discovery rooted at the target's
directory) and a zero-test run is an error, never a
verdict. This probe now asserts the FIXED behaviour: the
identical failing test probes "fail" with AND without the
__main__ guard, agreeing with the runner control both
ways."""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import probe  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS,
                   "shadow-test-runner-4cf81c69d7cf.txt")

TEST_BODY = '''import unittest


class DemoTest(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(1, 2)
'''
GUARD = '\n\nif __name__ == "__main__":\n    unittest.main()\n'

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def build_tree(guard):
    tree = tempfile.mkdtemp(prefix="codereview-testprobe-")
    os.makedirs(os.path.join(tree, "tests"))
    with open(os.path.join(tree, "tests", "test_demo.py"),
              "w") as fh:
        fh.write(TEST_BODY + (GUARD if guard else ""))
    return tree


outcomes = {}
for label, guard in (("A — failing test WITH __main__ guard",
                      True),
                     ("B — same failing test, NO guard",
                      False)):
    tree = build_tree(guard)
    try:
        res = probe.run_probe(
            {"kind": "test", "target": "tests/test_demo.py"},
            tree, timeout=60)
        outcomes[label] = res["outcome"]
        ctl = subprocess.run(
            [sys.executable, "-m", "unittest", "discover",
             "-s", "tests"], cwd=tree, capture_output=True,
            text=True, timeout=60)
        ctl_lines = (ctl.stderr or "").strip().splitlines()
        ctl_tail = ctl_lines[-1] if ctl_lines else ""
        ctl_word = "FAILED" if ctl.returncode else "OK"
        emit(f"{label}:")
        emit(f"  harness kind-'test' probe: outcome="
             f"{res['outcome']} exit={res['exit_code']}")
        emit(f"  unittest discover control: exit="
             f"{ctl.returncode} ({ctl_word} — {ctl_tail})")
    finally:
        shutil.rmtree(tree, ignore_errors=True)

test_files = sorted(
    f for f in os.listdir(os.path.join(REPO, "tests"))
    if f.startswith("test_") and f.endswith(".py"))
guarded, unguarded = [], []
for name in test_files:
    with open(os.path.join(REPO, "tests", name),
              encoding="utf-8") as fh:
        (guarded if "unittest.main" in fh.read()
         else unguarded).append(name)
emit("")
emit(f"repo convention at HEAD: {len(guarded)}/{len(test_files)} "
     f"files under tests/ carry the unittest.main guard; "
     f"without it: {unguarded}")

emit("")
assert outcomes["A — failing test WITH __main__ guard"] \
    == "fail", outcomes
assert outcomes["B — same failing test, NO guard"] \
    == "fail", outcomes
emit("VERDICT FACTS (post-fix): kind-'test' probes run "
     "through the unittest runner (discovery rooted at "
     "the target's directory) — the identical failing "
     "test probes 'fail' WITH and WITHOUT the __main__ "
     "guard, agreeing with the runner control both ways; "
     "a probe verdict no longer depends on a file-level "
     "guard the spec contract never required, and a run "
     "that executes zero tests is recorded as an error, "
     "never as a verdict. Pre-fix, the 'test' kind "
     "executed the target file as a script: without the "
     "guard the identical failing test probed 'pass', "
     "exit 0, ZERO tests executed, while the runner "
     "failed it (4cf81c69d7cf, sustained; fixed in the "
     "shadow-fixes branch).")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
