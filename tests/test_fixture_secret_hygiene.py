"""Regression guard: the test suite's own fixtures must never
trip the deterministic secret rules.

The hardcoded-secret blocker (finding 44a6ae2d215a) fired on
fake key strings in test fixtures three times — each time a
review caught what the suite itself should have caught. The
rule is correct (it cannot tell a fixture fake from a real
leaked key, and it must not be weakened); the fixtures are what
must stay clean. Where a test needs a secret-shaped value at
runtime (the scanner and redaction tests), it assembles the
value from fragments so no literal line matches — see
tests/test_core.py and tests/test_external_review_v070.py.

This test runs the product's OWN deterministic scan, with its
own placeholder exemption, over every line of every file under
tests/ presented as added diff lines — exactly what a review
of a change to the test suite would see — plus a raw scan for
bare OpenAI-shaped key literals that the assignment-shaped
rule does not cover. Any hit fails the suite here, not a
review later.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

SECRET_RULE_IDS = {"hardcoded-secret", "aws-access-key",
                   "private-key"}
BARE_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _test_files():
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")):
                continue
            yield os.path.join(root, name)


def _as_added_patch(path, lines):
    rel = os.path.relpath(
        path, os.path.dirname(TESTS_DIR)).replace(os.sep, "/")
    header = (f"diff --git a/{rel} b/{rel}\n"
              f"--- a/{rel}\n"
              f"+++ b/{rel}\n"
              f"@@ -0,0 +1,{len(lines)} @@\n")
    return header + "".join("+" + line + "\n" for line in lines)


class FixtureSecretHygieneTests(unittest.TestCase):
    def test_no_test_file_trips_the_secret_rules(self):
        offenders = []
        for path in _test_files():
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            findings = core.deterministic_scan(
                _as_added_patch(path, lines))
            for finding in findings:
                if finding["rule"] in SECRET_RULE_IDS:
                    offenders.append(
                        f"{path}:{finding['line']} "
                        f"{finding['rule']}")
            for lineno, line in enumerate(lines, 1):
                if BARE_KEY_RE.search(line):
                    offenders.append(
                        f"{path}:{lineno} bare key-shaped literal")
        self.assertEqual(
            offenders, [],
            "test fixtures must not contain secret-shaped "
            "literals; assemble fake values from fragments "
            "instead (see tests/test_core.py)")
