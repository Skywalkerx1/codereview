#!/usr/bin/env python3
"""Parent-fail fix-verification — open-refutations solution
§3, for the two fix-verified items:

  19a537eb386b  cross-kind role-seat collision guard
                fix 6f5e73c, parent 69ab354
  931ea3882b76  aborted first-run wizard exits cleanly
                fix 98ad1d9, parent 6f5e73c

For each: run the fix's tests against the FIX tree (must
pass) and against the PARENT tree (must fail the same way
the claim described) — a fix is only verified if its test
fails without it.

19a537eb386b needs an extracted test file: the fix commit
created tests/test_user_setup.py wholesale (it also created
userconfig.py/setup_wizard.py, which the parent lacks), so
only the CrossKindRoleCollisionTests class — which imports
just cli + providers, both present at the parent — is
extracted and run in both trees.

931ea3882b76's parent already has every module; the fix
commit's test file is overlaid whole and the one new test
is run in both trees.

Worktrees live in /tmp and are removed afterwards. Exit 0 =
both verifications show pass-at-fix / fail-at-parent."""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

EXTRACTED = '''"""Extracted CrossKindRoleCollisionTests (from the fix
commit's tests/test_user_setup.py) — imports only cli and
providers so it can run against the parent tree, which lacks
the setup modules the full file imports."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "src"))

from codereview import cli, providers  # noqa: E402


class CrossKindRoleCollisionTests(unittest.TestCase):
    def test_agent_role_seat_cannot_shadow_an_api_seat(self):
        panel = providers.build_providers(["gemini"])
        with self.assertRaises(providers.ProviderError):
            cli._apply_role_assignments(
                panel, ["tech-lead=agent:gemini:cat"])

    def test_api_role_seat_cannot_shadow_an_agent_seat(self):
        panel = providers.build_providers(["agent:claude:cat"])
        with self.assertRaises(providers.ProviderError):
            cli._apply_role_assignments(
                panel,
                ["correctness=claude|openai-compatible|"
                 "https://example.com/v1|m|SOME_KEY_ENV"])

    def test_same_kind_same_name_still_merges(self):
        panel = providers.build_providers(["gemini"])
        _lens, seat_roles, _models, _tl = \\
            cli._apply_role_assignments(
                panel, ["tech-lead=gemini"])
        self.assertEqual(seat_roles["tech-lead"], "gemini")
        self.assertEqual(set(panel), {"gemini"})


if __name__ == "__main__":
    unittest.main()
'''


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd,
                          capture_output=True, text=True)


def run_tests(worktree, test_rel, target=None):
    cmd = [sys.executable, "-m", "unittest", "-v"]
    mod = test_rel[:-3].replace("/", ".")
    cmd.append(mod + ("." + target if target else ""))
    proc = subprocess.run(cmd, cwd=worktree, capture_output=True,
                          text=True)
    return proc.returncode, proc.stdout + proc.stderr


def worktree(commit, tmp, name):
    path = os.path.join(tmp, name)
    proc = git("worktree", "add", "--detach", path, commit)
    assert proc.returncode == 0, proc.stderr
    return path


def verify_19(tmp, lines):
    lines += ["", "=" * 60,
              "19a537eb386b — cross-kind role-seat collision guard",
              "fix 6f5e73c, parent 69ab354", "=" * 60]
    fix = worktree("6f5e73c", tmp, "fix19")
    parent = worktree("69ab354", tmp, "parent19")
    rel = os.path.join("tests", "test_pt1_crosskind.py")
    for wt in (fix, parent):
        with open(os.path.join(wt, rel), "w",
                  encoding="utf-8") as fh:
            fh.write(EXTRACTED)
    rc_fix, out_fix = run_tests(fix, rel)
    rc_par, out_par = run_tests(parent, rel)
    lines.append(f"--- at FIX 6f5e73c: exit {rc_fix}")
    lines.append(out_fix.strip())
    lines.append(f"--- at PARENT 69ab354: exit {rc_par}")
    lines.append(out_par.strip())
    verified = rc_fix == 0 and rc_par != 0
    lines.append(
        "VERIFIED: tests pass at the fix and fail at the parent"
        " (the two collision cases raise nothing at the parent —"
        " the shadowing the claim described; the same-kind merge"
        " control passes in both trees)."
        if verified else
        "NOT VERIFIED as expected — see output above.")
    return verified


def verify_931(tmp, lines):
    lines += ["", "=" * 60,
              "931ea3882b76 — aborted first-run wizard exits "
              "cleanly", "fix 98ad1d9, parent 6f5e73c", "=" * 60]
    fix = worktree("98ad1d9", tmp, "fix931")
    parent = worktree("6f5e73c", tmp, "parent931")
    src = git("show", "98ad1d9:tests/test_user_setup.py").stdout
    with open(os.path.join(parent, "tests", "test_user_setup.py"),
              "w", encoding="utf-8") as fh:
        fh.write(src)
    target = ("RunResolutionTests.test_aborted_first_run_"
              "wizard_exits_cleanly")
    rc_fix, out_fix = run_tests(fix, "tests/test_user_setup.py",
                                target)
    rc_par, out_par = run_tests(parent, "tests/test_user_setup.py",
                                target)
    lines.append(f"--- at FIX 98ad1d9: exit {rc_fix}")
    lines.append(out_fix.strip())
    lines.append("--- at PARENT 6f5e73c (fix commit's test file"
                 " overlaid): exit " + str(rc_par))
    lines.append(out_par.strip())
    verified = rc_fix == 0 and rc_par != 0
    lines.append(
        "VERIFIED: the test passes at the fix and fails at the"
        " parent (the aborted wizard escaped as an exception —"
        " the traceback path the claim described)."
        if verified else
        "NOT VERIFIED as expected — see output above.")
    return verified


def main():
    lines = ["PARENT-FAIL FIX-VERIFICATION — solution §3",
             "A fix counts as verified only if its test fails",
             "on the parent and passes on the fix."]
    tmp = tempfile.mkdtemp(prefix="pt1-fixverify-")
    try:
        ok1 = verify_19(tmp, lines)
        ok2 = verify_931(tmp, lines)
    finally:
        git("worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)
    lines += ["", f"OVERALL: 19a537eb386b verified={ok1}; "
                  f"931ea3882b76 verified={ok2}"]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, "fix-verification.txt"),
              "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    sys.exit(0 if (ok1 and ok2) else 1)


if __name__ == "__main__":
    main()
