#!/usr/bin/env python3
"""Closing-B probe — 887c490bd9eb (attempt-2): "New CLI
commands added without test coverage."

Method (refined after a first raw-grep pass proved too
loose in both directions): for every subcommand dispatched
by cli.main (cli.py:1674-1712), search tests/ for a
FUNCTIONAL exercise of its CLI entry — cli.main(["<sub>",
...]), cli._<sub>_main(...), a subprocess invocation of
the module with the subcommand, or (setup only) cli.main
with the wizard seam the subcommand owns. Engine-level
unit tests of the underlying module are noted separately:
they cover the machinery, not the subcommand's own
argument handling / exit-code surface.

Writes results/closingB-cli-coverage.txt. Facts only.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

OUT = os.path.join(HERE, "results", "closingB-cli-coverage.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


# subcommand -> regexes that count as a functional CLI-entry
# exercise in a test file
PATTERNS = {
    "setup": [r"_run_setup_wizard", r"_setup_main",
              r'main\(\[\s*"setup"'],
    "evidence": [r"_evidence_main", r'main\(\[\s*"evidence"',
                 r'"codereview\.cli",\s*"evidence"'],
    "acceptance": [r"_acceptance_main",
                   r'main\(\[\s*"acceptance"'],
    "doctor": [r"_doctor_main", r'main\(\[\s*"doctor"'],
    "record-verify": [r"_record_verify_main",
                      r'main\(\[\s*"record-verify"',
                      r'"codereview\.cli",\s*"record-verify"',
                      r'"record-verify",\s*"--'],
    "policy": [r'main\(\[\s*"policy"', r"_policy_main",
               r'\[\s*"policy",\s*"check"'],
    "sarif": [r'main\(\[\s*"sarif"', r"_sarif_main"],
    "disputes": [r'main\(\[\s*"disputes"', r"_disputes_main"],
    "locate": [r'main\(\[\s*"locate"', r"_locate_main",
               r'\["locate",'],
    "bench": [r'main\(\[\s*"bench"', r"_bench_main"],
    "pr": [r'main\(\[\s*"pr"', r"_pr_main\("],
    "workflow": [r'main\(\[\s*"workflow"', r"_workflow_main\("],
    "loop": [r'main\(\[\s*"loop"', r"_loop_main\("],
    "intake": [r'main\(\[\s*"intake"', r"_intake_main\("],
}

ENGINE_ONLY = {
    "evidence": "evidence.collect/verify_claims unit-tested "
                "directly in tests/test_evidence.py",
    "acceptance": "acceptance.run_acceptance unit-tested "
                  "directly in tests/test_shadow_acceptance.py",
    "pr": "github fetch machinery in tests/test_github.py; "
          "_pr_main appears only in test_v091_fixes.py's "
          "structural NO_TIMEOUT_OPTION enumeration",
    "workflow": "_workflow_main appears only in "
                "test_v091_fixes.py's structural enumeration",
    "loop": "core.run_loop engine-tested in "
            "tests/test_core.py; _loop_main appears only "
            "in the same structural enumeration",
}


def main():
    say("CLI COVERAGE PROBE — 887c490bd9eb")
    say("functional CLI-entry exercise per subcommand "
        "(cli.py:1674-1712 dispatch)")
    tests_dir = os.path.join(REPO, "tests")
    files = sorted(f for f in os.listdir(tests_dir)
                   if f.startswith("test_") and f.endswith(".py"))
    texts = {}
    for f in files:
        with open(os.path.join(tests_dir, f),
                  encoding="utf-8") as fh:
            texts[f] = fh.read()
    for sub, pats in PATTERNS.items():
        hits = [f for f, text in texts.items()
                if any(re.search(p, text) for p in pats)]
        say(f"  {sub:<14} functional CLI tests: "
            f"{', '.join(hits) if hits else 'NONE'}")
        if not hits and sub in ENGINE_ONLY:
            say(f"  {'':<14} engine-only coverage: "
                f"{ENGINE_ONLY[sub]}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
