"""Claim lint (honest-negatives solution §2.6): the caveat
travels with the headline — enforced, not just intended.

Every baseline file carries a machine-readable
`required_caveat`. The guarded files below may quote the
baseline's headline figures only with that caveat adjacent —
embedded verbatim, or via a reference to the baseline file
that carries it. And the superseded naive precision figure
(step-3 recount, 2026-11-04) may never appear as a current
claim: in any guarded file it may only show up AFTER the file
has marked it superseded (the baseline's frontmatter caveat
and repair pointer do this for its own historical sections;
the CHANGELOG's Unreleased entry does it for the 0.12.0
entry's as-published figures).

The check is deliberately pragmatic: an explicit, small
guarded-file list and literal figure patterns. It guards the
docs that carry claims — README.md, CHANGELOG.md, and the
baseline itself — not every text in the repo.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))
BASELINE_REL = os.path.join("bench", "BASELINE-2026-11-04.md")
GUARDED = ("README.md", "CHANGELOG.md", BASELINE_REL)

# The baseline's headline figures, as literal text. A guarded
# doc quoting any of these owes the reader the caveat (or the
# baseline reference that carries it).
HEADLINE_PATTERNS = (
    r"34/34",
    r"24/24",
    r"0\.870",
    r"0\.756",
    r"0\.956",
    r"0\.906",
    r"[Rr]ecall[^\n]{0,60}1\.000",
)

NAIVE_FIGURE = "0.209"
BASELINE_REF = "bench/BASELINE-2026-11-04.md"


def read_repo(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def required_caveat(baseline_text):
    """The baseline frontmatter's required_caveat string, or
    None. Read from the baseline itself — never duplicated."""
    m = re.search(r'^required_caveat:\s*"(.*)"\s*$',
                  baseline_text, re.MULTILINE)
    return m.group(1) if m else None


def claim_violations(texts):
    """texts: {rel_path: text} -> list of violation strings.

    Rules:
    (a) a guarded file other than the baseline that mentions a
        headline figure must embed the required_caveat
        verbatim or reference the baseline file;
    (b) the superseded naive figure may appear in a guarded
        file only after that file has marked it superseded
        (the word 'superseded' occurs earlier in the file).
    """
    violations = []
    caveat = required_caveat(texts[BASELINE_REL])
    if not caveat:
        return [f"{BASELINE_REL}: no required_caveat in the "
                f"frontmatter — the lint has nothing to enforce"]
    for rel in GUARDED:
        text = texts[rel]
        if rel != BASELINE_REL:
            quoted = [p for p in HEADLINE_PATTERNS
                      if re.search(p, text)]
            if quoted and caveat not in text \
                    and BASELINE_REF not in text:
                violations.append(
                    f"{rel}: quotes headline figure(s) "
                    f"{quoted} without the baseline's "
                    f"required_caveat embedded or a reference "
                    f"to {BASELINE_REF}")
        idx = text.find(NAIVE_FIGURE)
        if idx >= 0 and "superseded" not in text[:idx].lower():
            violations.append(
                f"{rel}: the superseded naive figure "
                f"{NAIVE_FIGURE} appears before the file marks "
                f"it superseded — it must never read as a "
                f"current claim")
    return violations


class ClaimLintTests(unittest.TestCase):
    def test_baseline_carries_a_real_caveat(self):
        caveat = required_caveat(read_repo(BASELINE_REL))
        self.assertIsNotNone(caveat)
        self.assertGreater(len(caveat), 200)
        # The caveat itself retires the naive figure.
        self.assertIn("superseded", caveat)
        self.assertIn("do not quote", caveat)

    def test_guarded_docs_pass_the_lint(self):
        texts = {rel: read_repo(rel) for rel in GUARDED}
        self.assertEqual(claim_violations(texts), [])

    def test_lint_bites_on_a_bare_headline_quote(self):
        texts = {rel: read_repo(rel) for rel in GUARDED}
        texts["README.md"] = "Recall 34/34, precision 0.870!\n"
        violations = claim_violations(texts)
        self.assertTrue(any("README.md" in v for v in violations))

    def test_lint_bites_on_unmarked_naive_figure(self):
        texts = {rel: read_repo(rel) for rel in GUARDED}
        texts["CHANGELOG.md"] = "## 9.9.9\n\nPrecision 0.209.\n"
        violations = claim_violations(texts)
        self.assertTrue(
            any("CHANGELOG.md" in v for v in violations))

    def test_lint_accepts_a_baseline_reference(self):
        texts = {rel: read_repo(rel) for rel in GUARDED}
        texts["README.md"] = (
            "Recall 34/34 on the public split — see "
            "bench/BASELINE-2026-11-04.md for the caveat.\n")
        self.assertEqual(claim_violations(texts), [])


if __name__ == "__main__":
    unittest.main()
