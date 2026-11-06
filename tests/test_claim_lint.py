"""Claim lint (honest-negatives solution §2.6): the caveat
travels with the headline — enforced, not just intended.

Strengthened after the external Phase 5 report (P5-08): the
original lint checked three files at FILE level (one caveat
anywhere cleared every claim in the file) with a few literal
patterns; 11 of 11 unqualified claim variants the tester
appended to the README passed it. The lint now works at
PARAGRAPH level over every shipped reader-facing doc:

- Scope: README.md, CHANGELOG.md, ROADMAP.md, REVIEW-NOTES.md
  and THREAT-MODEL.md at the root, every bench/*.md and every
  pilot/*.md — minus the named RECORD docs below. Records of
  registered runs are immutable evidence: they state what was
  measured and claimed at the time and are never edited to
  satisfy a lint, so they are out of scope BY NAME, with the
  reason recorded here. (The root review-*.md response and
  disposition files and gate-attempts.md are likewise
  historical adjudication records and are not in the root set.)
- A claim is a paragraph (blank-line-delimited block, matched
  whitespace-normalised) that states a headline figure: the
  baseline's corrected decimals, a perfect N/N fraction, or a
  recall-perfection phrasing (decimal, percentage or words).
- A claim paragraph is qualified only by material IN THE SAME
  paragraph: a reference to the baseline document that carries
  the required caveat, the caveat itself, or an explicit
  in-place caveat pointer ("see the asymmetry caveat in §2.1").
  A caveat elsewhere in the file no longer clears it.
- The superseded naive precision figure (0.209, step-3
  recount, 2026-11-04) may never read as a current claim: it
  may appear only after the file has marked it superseded,
  and a paragraph that presents it as current ("Current
  precision is 0.209") fails even then unless the same
  paragraph marks it superseded.
- The baseline document itself is the caveat source and a
  registered record: it is exempt from the claim-figure rule
  and held only to the naive-figure ordering rule.
"""

import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))
BASELINE_REL = os.path.join("bench", "BASELINE-2026-11-04.md")
BASELINE_REF = "bench/BASELINE-2026-11-04.md"

ROOT_GUARDED = ("README.md", "CHANGELOG.md", "ROADMAP.md",
                "REVIEW-NOTES.md", "THREAT-MODEL.md")

# Records of registered runs: immutable, out of scope by name.
RECORD_DOCS = frozenset({
    os.path.join("bench", "BASELINE-V2-2026-11-05.md"),
    os.path.join("bench", "baseline-2026-11-04-report.md"),
})


def guarded_files():
    rels = set(ROOT_GUARDED)
    for pattern in (os.path.join("bench", "*.md"),
                    os.path.join("pilot", "*.md")):
        for path in glob.glob(os.path.join(REPO_ROOT, pattern)):
            rels.add(os.path.relpath(path, REPO_ROOT))
    rels.discard(BASELINE_REL)
    return sorted(rels - RECORD_DOCS)


# Claim patterns, matched against a whitespace-normalised
# paragraph. Decimals and percentages for the recall figure,
# the corrected headline decimals, and perfection phrasings.
CLAIM_PATTERNS = (
    r"0\.870",
    r"0\.756",
    r"0\.956",
    r"0\.906",
    r"[Rr]ecall[^0-9]{0,30}?\b1(?:\.0+)?\b",
    r"[Rr]ecall[^0-9]{0,30}?\b100\s*%",
    r"\b100\s*%\s+[Rr]ecall",
    r"[Pp]erfect recall",
    r"[Cc]atches every bug",
    r"[Zz]ero false positives",
)

# A perfect N/N fraction is a claim only in a LOCAL metric
# context (and only for case-sized counts): suite sizes
# ("full suite 1005/1005"), chain/record counts and narrative
# mentions in engineering entries are not benchmark claims.
FRACTION_PATTERN = r"\b(\d{1,2})/\1\b"
FRACTION_CONTEXT = (r"recall|precision|defect|clean[- ]case|"
                    r"benchmark|corpus|split|stratum|baseline")
FRACTION_WINDOW = 80

# In-paragraph qualification, in the docs' own established
# vocabulary: a reference to a baseline document that carries
# the caveat, the caveat's own name, an in-place caveat
# pointer, a superseded marking, the claims sheet's mandatory-
# caveats formula, a harness-validation scope line for the
# scripted replay seats, or an explicit not-a-claim
# disclaimer in the same paragraph.
QUALIFIER_PATTERNS = (
    r"BASELINE-2026-11-04",
    r"BASELINE-V2-2026-11-05",
    r"required[ _]caveat",
    r"(see|in|the)\s+(the\s+)?[\w ]{0,30}caveat|caveat\s+in",
    r"superseded",
    r"[Mm]andatory caveats",
    r"validates? the harness",
    r"not (a |an |any )?(confirmed result|product claim|"
    r"independent recall measurement)",
)

NAIVE_FIGURE = "0.209"


def read_repo(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def required_caveat(baseline_text):
    """The baseline frontmatter's required_caveat string, or
    None. Read from the baseline itself — never duplicated."""
    m = re.search(r'^required_caveat:\s*"(.*)"\s*$',
                  baseline_text, re.MULTILINE)
    return m.group(1) if m else None


def _paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _normalised(paragraph):
    return " ".join(paragraph.split())


def _qualified(paragraph, caveat):
    if caveat and caveat in paragraph:
        return True
    return any(re.search(p, paragraph, re.IGNORECASE)
               for p in QUALIFIER_PATTERNS)


def claim_violations(texts):
    """texts: {rel_path: text} covering the guarded files plus
    the baseline -> list of violation strings."""
    violations = []
    caveat = required_caveat(texts[BASELINE_REL])
    if not caveat:
        return [f"{BASELINE_REL}: no required_caveat in the "
                f"frontmatter — the lint has nothing to enforce"]
    for rel in sorted(texts):
        if rel == BASELINE_REL:
            continue
        text = texts[rel]
        for paragraph in _paragraphs(text):
            norm = _normalised(paragraph)
            hits = [p for p in CLAIM_PATTERNS
                    if re.search(p, norm)]
            for m in re.finditer(FRACTION_PATTERN, norm):
                window = norm[max(0, m.start() - FRACTION_WINDOW):
                              m.end() + FRACTION_WINDOW]
                if re.search(FRACTION_CONTEXT, window,
                             re.IGNORECASE):
                    hits.append(FRACTION_PATTERN)
                    break
            if hits and not _qualified(norm, caveat):
                violations.append(
                    f"{rel}: unqualified claim "
                    f"(pattern {hits[0]!r}) in paragraph: "
                    f"{norm[:110]}...")
        # The naive figure: file-order rule (must be marked
        # superseded earlier in the file) plus the paragraph
        # currency rule.
        idx = text.find(NAIVE_FIGURE)
        if idx >= 0 and "superseded" not in text[:idx].lower():
            violations.append(
                f"{rel}: the superseded naive figure "
                f"{NAIVE_FIGURE} appears before the file marks "
                f"it superseded — it must never read as a "
                f"current claim")
        for paragraph in _paragraphs(text):
            norm = _normalised(paragraph)
            if NAIVE_FIGURE in norm \
                    and re.search(r"[Cc]urrent", norm) \
                    and "superseded" not in norm.lower():
                violations.append(
                    f"{rel}: the superseded naive figure "
                    f"{NAIVE_FIGURE} is presented as current "
                    f"in paragraph: {norm[:110]}...")
    # The baseline itself is held to the ordering rule only.
    base = texts[BASELINE_REL]
    idx = base.find(NAIVE_FIGURE)
    if idx >= 0 and "superseded" not in base[:idx].lower():
        violations.append(
            f"{BASELINE_REL}: the superseded naive figure "
            f"{NAIVE_FIGURE} appears before the frontmatter "
            f"caveat marks it superseded")
    return violations


def load_texts():
    texts = {rel: read_repo(rel) for rel in guarded_files()}
    texts[BASELINE_REL] = read_repo(BASELINE_REL)
    return texts


# The Phase 5 tester's mutation set: every one of these,
# appended to the README, must now FAIL the lint.
MUTATION_VARIANTS = (
    "Our reviewers reach recall 1.0 on the corpus.",
    "Recall 1.000 on the public split.",
    "Recall = 1.00 across the corpus.",
    "The panel achieves a recall of 100%.",
    "Perfect recall on every case.",
    "CodeReview catches every bug.",
    "It caught 34/34 seeded defects.",
    "Current precision is 0.209.",
    "**Recall: 1.0** on the benchmark.",
    "Recall\n1.0",
    "Zero false positives in testing.",
)


class ClaimLintTests(unittest.TestCase):
    def test_baseline_carries_a_real_caveat(self):
        caveat = required_caveat(read_repo(BASELINE_REL))
        self.assertIsNotNone(caveat)
        self.assertGreater(len(caveat), 200)
        # The caveat itself retires the naive figure.
        self.assertIn("superseded", caveat)
        self.assertIn("do not quote", caveat)

    def test_scope_is_the_shipped_docs_minus_records(self):
        guarded = guarded_files()
        for expected in ("README.md", "CHANGELOG.md",
                         os.path.join("bench", "CLAIMS-SHEET.md"),
                         os.path.join("bench",
                                      "PUBLIC-BENCHMARK.md"),
                         os.path.join("pilot", "QUICKSTART.md")):
            self.assertIn(expected, guarded)
        for record in RECORD_DOCS:
            self.assertNotIn(record, guarded)

    def test_guarded_docs_pass_the_lint(self):
        self.assertEqual(claim_violations(load_texts()), [])

    def test_every_phase5_mutation_variant_fails(self):
        for variant in MUTATION_VARIANTS:
            texts = load_texts()
            texts["README.md"] += "\n\n" + variant + "\n"
            violations = claim_violations(texts)
            self.assertTrue(
                any("README.md" in v for v in violations),
                f"mutation not caught: {variant!r}")

    def test_caveat_elsewhere_in_file_no_longer_clears(self):
        texts = load_texts()
        texts["README.md"] = (
            "See bench/BASELINE-2026-11-04.md for the caveat."
            "\n\nRecall 1.0 on the corpus.\n")
        violations = claim_violations(texts)
        self.assertTrue(any("README.md" in v for v in violations))

    def test_same_paragraph_baseline_reference_qualifies(self):
        texts = load_texts()
        texts["README.md"] = (
            "Recall 34/34 on the public split — see "
            "bench/BASELINE-2026-11-04.md for the caveat.\n")
        self.assertEqual(claim_violations(texts), [])


if __name__ == "__main__":
    unittest.main()
