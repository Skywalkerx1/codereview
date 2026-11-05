#!/usr/bin/env python3
"""Hardening parent-fail verification — for the three
hardening fixes in commit c1bf1df (parent: probes commit
7c73fbf):

  4ce0212286e0  _prompt_slice truncation marker
  6b29fe953939  fail-safe callee key
  9a4415ddafa6  load_user_config type validation

Runs tests/test_v111_hardening.py (overlaid from HEAD) in a
worktree at the parent commit: the tests for each fix must
FAIL there while the behaviour-preservation controls pass —
proving the tests pin the fix, not the status quo. The
non-dict test (bf4c451e8751) must PASS at the parent: the
guard predates the track, which is exactly the packet's
point (conclusion holds, mechanism corrected).

Exit 0 = the expected pass/fail pattern held."""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
PARENT = "7c73fbf"

EXPECT_FAIL = {
    "test_ambiguous_name_keys_to_all_candidates",
    "test_self_call_resolves_to_the_method",
    "test_finding_public_marks_long_evidence",
    "test_over_cap_marker_complete_and_boundary_clean",
    "test_single_long_word_still_marked",
    "test_under_cap_unchanged",
    "test_providers_wrong_types_raise_value_error",
    "test_roles_wrong_types_raise_value_error",
}
EXPECT_PASS = {
    "test_unambiguous_name_keeps_bare_hash",
    "test_nested_sibling_resolution",
    "test_missing_and_valid_configs",
    "test_sidecar_walk_skips_non_dicts_and_serves_dicts",
}


def main():
    tmp = tempfile.mkdtemp(prefix="pt1-hardening-pf-")
    wt = os.path.join(tmp, "wt")
    lines = ["HARDENING PARENT-FAIL VERIFICATION",
             f"Test file from HEAD overlaid on parent {PARENT} "
             "(pre-hardening).", ""]
    try:
        subprocess.run(["git", "worktree", "add", "--detach",
                        wt, PARENT], cwd=REPO, check=True,
                       capture_output=True, text=True)
        shutil.copy(os.path.join(
            REPO, "tests", "test_v111_hardening.py"),
            os.path.join(wt, "tests", "test_v111_hardening.py"))
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "-v",
             "tests.test_v111_hardening"],
            cwd=wt, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
    finally:
        subprocess.run(["git", "worktree", "remove", "--force",
                        wt], cwd=REPO, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    status = {}
    for ln in out.splitlines():
        if " (tests.test_v111_hardening." in ln and \
                (" ... ok" in ln or " ... FAIL" in ln
                 or " ... ERROR" in ln):
            name = ln.split(" (")[0].strip()
            status[name] = ln.rsplit(" ", 1)[-1]
    for name in sorted(status):
        lines.append(f"  {name}: {status[name]}")
    bad = [n for n in EXPECT_FAIL if status.get(n) == "ok"] + \
          [n for n in EXPECT_PASS if status.get(n) != "ok"]
    lines += ["",
              "Pattern check: fix tests fail at parent = "
              f"{not any(status.get(n) == 'ok' for n in EXPECT_FAIL)}"
              "; controls + non-dict test pass at parent = "
              f"{all(status.get(n) == 'ok' for n in EXPECT_PASS)}",
              "VERIFIED: each hardening fix is pinned by a "
              "parent-failing test; bf4c451e8751's guard "
              "predates the track (passes in both trees)."
              if not bad else
              f"PATTERN BROKEN for: {bad}"]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "hardening-parent-fail.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
