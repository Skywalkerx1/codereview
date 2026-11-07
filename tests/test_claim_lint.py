"""Claim lint (honest-negatives solution §2.6): the caveat
travels with the headline — enforced, not just intended.

Strengthened after the external Phase 5 report (P5-08): the
original lint checked three files at FILE level (one caveat
anywhere cleared every claim in the file) with a few literal
patterns; 11 of 11 unqualified claim variants the tester
appended to the README passed it. The lint now works at
PARAGRAPH level over every shipped reader-facing doc:

- Scope: every tracked *.md in the tree (recursive glob) —
  the root docs, bench/*.md, pilot/*.md, docs/, skills/,
  the herdr plugin README, probes/ — minus the RECORDS
  below. Widened after the Phase 5 rerun (P5-08b): the fixed
  root+bench+pilot set let any claim in docs/*.md (and any
  other unlisted directory) sail past the lint.
- Records are out of scope, by name and by tree, with the
  reason recorded here: records of registered runs are
  immutable evidence — they state what was measured and
  claimed at the time and are never edited to satisfy a
  lint. That covers the two named baseline records, the
  registered-run stores (bench/sealed/, bench/generation-v2/,
  bench/generation-v3/, bench/confirmation-b2/,
  bench/confirmation-v2/), the dated analysis/pilot/provenance
  record trees under bench/, the acceptance-run scorecard,
  the pilot demo sample records, and the tests/ fixtures.
  The root review-* files and directories and gate-attempts.md
  are likewise historical adjudication records.
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
- The limit of the approach, stated plainly (P5-08d): this
  lint is a phrase list. The pattern table enumerates the
  claim wordings seen so far — each rerun has produced
  evasions the previous table missed (P5-08b, P5-08c) — and
  any genuinely new wording passes until it is added. The
  lint is a tripwire over known phrasings, not a proof that
  a document makes no unqualified claim; the discipline it
  backs up (the caveat travels with the headline) remains
  the docs authors' obligation, and no pattern table
  discharges it.
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

# Records of registered runs: immutable, out of scope by name.
RECORD_DOCS = frozenset({
    os.path.join("bench", "BASELINE-V2-2026-11-05.md"),
    os.path.join("bench", "baseline-2026-11-04-report.md"),
})

# Record TREES: registered-run stores and dated run artefacts.
# Same principle as RECORD_DOCS — immutable evidence, never
# edited to satisfy a lint.
RECORD_DIRS = (
    os.path.join("bench", "sealed"),
    os.path.join("bench", "generation-v2"),
    os.path.join("bench", "generation-v3"),
    os.path.join("bench", "confirmation-b2"),
    os.path.join("bench", "confirmation-v2"),
    os.path.join("bench", "analysis-2026-11-05"),
    os.path.join("bench", "expanded-clean"),
    os.path.join("bench", "pilot-b2-2026-11-05"),
    os.path.join("bench", "real-world"),
    os.path.join("acceptance-run-2026-11-04"),
    os.path.join("pilot", "demo"),
    "test-runs",
    "tests",
)


def _is_record(rel):
    """True when a repo-relative *.md path is a record, not a
    shipped reader-facing doc (see the scope note above)."""
    if rel in RECORD_DOCS or rel == "gate-attempts.md":
        return True
    parts = rel.split(os.sep)
    # Historical adjudication records: the root review-*
    # response files and run-output directories. (Case matters:
    # REVIEW-NOTES.md is a guarded doc, not a record.)
    if parts[0].startswith("review-"):
        return True
    # Runtime caches are not tracked docs.
    if any(c in ("cache", "__pycache__") or c.endswith("-cache")
           for c in parts):
        return True
    for prefix in RECORD_DIRS:
        pp = prefix.split(os.sep)
        if parts[:len(pp)] == pp:
            return True
    return False


def guarded_files():
    rels = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "**", "*.md"),
                          recursive=True):
        rel = os.path.relpath(path, REPO_ROOT)
        if not _is_record(rel):
            rels.add(rel)
    rels.discard(BASELINE_REL)
    return sorted(rels)


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
    # P5-08b: the phrasing families the rerun evaded with.
    # The reversed decimal needs the lookbehind: "attempt-1
    # recall point" is prose about a run, not a claim.
    r"(?<![\w-])1(?:\.0+)?\s+[Rr]ecall\b",
    r"[Rr]ecall of (?:one|1(?:\.0+)?)\b",
    r"\ball\s+\d{1,3}\s+(?:seeded|planted)\s+"
    r"(?:defects|bugs|cases|findings)\b",
    r"\bno misses\b",
    r"\bnever misses\b",
)

# A perfect N/N fraction is a claim only in a LOCAL metric
# context (and only for case-sized counts): suite sizes
# ("full suite 1005/1005"), chain/record counts and narrative
# mentions in engineering entries are not benchmark claims.
FRACTION_PATTERN = r"\b(\d{1,2})/\1\b"
FRACTION_CONTEXT = (r"recall|precision|defect|clean[- ]case|"
                    r"benchmark|corpus|split|stratum|baseline")
FRACTION_WINDOW = 80

# "100% of …" is an all-of-set perfection claim only in a
# LOCAL metric context, under the same window discipline as
# the fraction rule (P5-08b): "finds 100% of seeded defects"
# is a headline claim; a bare percentage in unrelated prose
# is not.
ALL_OF_PATTERN = r"\b100\s*%\s+of\b"
ALL_OF_CONTEXT = (r"defect|bug|finding|seeded|planted|"
                  r"recall|case|vulnerab|flaw")

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
            for m in re.finditer(ALL_OF_PATTERN, norm):
                window = norm[max(0, m.start() - FRACTION_WINDOW):
                              m.end() + FRACTION_WINDOW]
                if re.search(ALL_OF_CONTEXT, window,
                             re.IGNORECASE):
                    hits.append(ALL_OF_PATTERN)
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

    def test_scope_widened_beyond_the_fixed_set(self):
        # P5-08b: the scope is the whole shipped doc set, not
        # the Phase 5 root+bench+pilot list — a claim in
        # docs/*.md (or skills/, or a plugin README) is linted
        # exactly like one in the README. Record trees and the
        # adjudication records stay out (see _is_record).
        guarded = guarded_files()
        for expected in (
                os.path.join("skills", "codereview", "SKILL.md"),
                os.path.join("herdr-plugin-codereview",
                             "README.md"),
                os.path.join("probes", "README.md")):
            self.assertIn(expected, guarded)
        for record in (
                os.path.join("bench", "sealed", "SEALED.md"),
                os.path.join("bench", "generation-v2",
                             "RESULTS-2026-11-05.md"),
                os.path.join("bench", "confirmation-b2",
                             "RESULTS-2026-11-06.md"),
                "gate-attempts.md",
                "review-v10-dispositions.md"):
            self.assertNotIn(record, guarded)
        self.assertFalse(_is_record(os.path.join("docs",
                                                  "X.md")))
        self.assertTrue(_is_record(
            os.path.join("bench", "sealed", "SEALED.md")))

    def test_claim_in_a_docs_file_fails(self):
        texts = load_texts()
        texts[os.path.join("docs", "GUIDE.md")] = (
            "We reach recall 1.0 on the corpus.\n")
        violations = claim_violations(texts)
        self.assertTrue(any("GUIDE.md" in v for v in violations))

    def test_every_phase5_rerun_variant_fails(self):
        # The rerun's evasion set (P5-08b): each appended to
        # the README must fail the lint.
        variants = (
            "The panel finds 100% of seeded defects.",
            "It caught all 34 seeded defects.",
            "A 1.0 recall on the public split.",
            "The gate has no misses.",
            "Recall of one on every case.",
        )
        for variant in variants:
            texts = load_texts()
            texts["README.md"] += "\n\n" + variant + "\n"
            violations = claim_violations(texts)
            self.assertTrue(
                any("README.md" in v for v in violations),
                f"rerun mutation not caught: {variant!r}")

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
