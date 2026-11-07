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
  whitespace-normalised and NFKC-normalised, so full-width
  digits and letters cannot disguise a figure) that states a
  headline figure: the baseline's corrected decimals, a
  perfect N/N or N-of-N fraction, or a recall-perfection
  phrasing (decimal, percentage or words).
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
- Profile attribution (W0, added after defect C1): the
  qualification rule above checks that SOME registered record
  is cited in the paragraph; it cannot check that a figure is
  attributed to the profile that actually produced it. C1
  was exactly that failure — the README's lead paragraph
  cited a record while giving the default `strict` gate the
  `balanced` profile's attempt-1 figures (precision 0.875,
  clean-BLOCKED 22/34 = 0.647), and `strict`'s own paired row
  (clean-BLOCKED 32/34) sat in the records unquoted. The lint
  now also carries a table of the registered runs' headline
  figures keyed to the profile of record: a paragraph that
  states one profile's figure while naming a DIFFERENT
  profile — and never the profile of record — fails. A
  paragraph naming both profiles (a comparison, a correction
  notice) is the legitimate form and passes. The table is
  enumerated, like the phrase list: a figure not in the table
  is not attribution-checked, and each new registered run's
  figures must be added to it by hand, with their source.
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
import unicodedata
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
    os.path.join("bench", "stage0-pc"),
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
    # P5-08c: the second rerun's families — the count-free
    # all-of-set ("found all seeded defects"), the spelled-
    # out percent, and the remaining perfection phrasings.
    r"\ball\s+(?:the\s+)?(?:seeded|planted)\s+"
    r"(?:defects|bugs|cases|findings)\b",
    r"[Rr]ecall[^0-9]{0,30}?\b100\s+percent\b",
    r"\b100\s+percent\s+[Rr]ecall\b",
    r"[Ff]alse[ -]positive[ -]free\b",
    r"\b[Zz]ero misses\b",
)

# A perfect N/N fraction is a claim only in a LOCAL metric
# context (and only for case-sized counts): suite sizes
# ("full suite 1005/1005"), chain/record counts and narrative
# mentions in engineering entries are not benchmark claims.
FRACTION_PATTERN = r"\b(\d{1,2})/\1\b"
FRACTION_CONTEXT = (r"recall|precision|defect|clean[- ]case|"
                    r"benchmark|corpus|split|stratum|baseline")
FRACTION_WINDOW = 80

# The same perfect fraction spelled with "of" ("caught 34
# of 34 seeded defects", P5-08c) is a claim under exactly
# the fraction rule's discipline: same local metric context,
# same window, same case-sized counts.
OF_PATTERN = r"\b(\d{1,2})\s+of\s+\1\b"

# "100% of …" is an all-of-set perfection claim only in a
# LOCAL metric context, under the same window discipline as
# the fraction rule (P5-08b): "finds 100% of seeded defects"
# is a headline claim; a bare percentage in unrelated prose
# is not.
ALL_OF_PATTERN = r"\b100\s*%\s+of\b"
ALL_OF_CONTEXT = (r"defect|bug|finding|seeded|planted|"
                  r"recall|case|vulnerab|flaw")

# Profile attribution (W0 / C1). PROFILE_TOKENS maps each
# gate profile to the tokens that name it in the shipped
# docs: the profile name itself, its policy alias (B1 / B2),
# and — for the two profiles the offline rule sweep scored —
# the sweep rule that reproduces it (R0 = strict, R1 = B1,
# glossed exactly that way wherever the sweep is reported).
# Word tokens match case-insensitively (sentence-initial
# "Strict"); the alias tokens (B1, B2, R0, R1) are
# case-sensitive — they are codes, not words.
PROFILE_TOKENS = {
    "strict": ((r"\bstrict\b", False), (r"\bR0\b", True)),
    "balanced": ((r"\bbalanced\b", False), (r"\bB1\b", True),
                 (r"\bR1\b", True)),
    "corroborated": ((r"\bcorroborated\b", False),
                     (r"\bB2\b", True)),
}

# The registered runs' headline figures, keyed to the
# profile of record. Sources: attempt 1 —
# bench/generation-v2/RESULTS-2026-11-05.md (scored rows +
# item 7.1's paired row) and the CLAIMS-SHEET paired-strict
# entry (precision 0.583, derived there); B2 confirmation —
# bench/confirmation-b2/RESULTS-2026-11-06.md via the
# CLAIMS-SHEET B2 entry. Recall in attempt 1 is deliberately
# absent: it is identical under `strict` and `balanced`
# (7 of 7 under both), so either profile may state it.
# Precision figures are matched only ADJACENT to the word
# "precision": the bare decimal 0.875 also appears as an
# unrelated J statistic in the B2 pilot row, and a bare
# decimal match would false-fire on it.
def _precision_adjacent(decimal):
    return (r"[Pp]recision[^0-9]{0,20}" + decimal
            + r"|" + decimal + r"[^0-9]{0,20}[Pp]recision")


PROFILE_FIGURES = (
    ("balanced", (
        r"0\.647", r"0\.657",
        r"22/34", r"22 of 34", r"23/35", r"23 of 35",
        r"65\s*%\s+of\s+clean",
        _precision_adjacent(r"0\.875"),
    )),
    ("strict", (
        r"0\.941",
        r"32/34", r"32 of 34",
        r"94\s*%\s+of\s+clean",
        r"0\.583",
    )),
    ("corroborated", (
        r"0\.292", r"0\.094", r"0\.778",
        r"7/24", r"7 of 24", r"6/64", r"6 of 64",
    )),
)


def _named_profiles(paragraph):
    named = set()
    for profile, tokens in PROFILE_TOKENS.items():
        for token, case_sensitive in tokens:
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(token, paragraph, flags):
                named.add(profile)
                break
    return named


def attribution_violations(rel, paragraph, context=frozenset()):
    """C1's failure mode: a paragraph states one profile's
    recorded figure while naming a different profile and
    never the profile of record. Naming both (a comparison
    or a correction) is the legitimate form and passes.
    `context` is the set of profiles named by the enclosing
    section headings: a results section headed for one
    profile attributes its own figures even when a closing
    paragraph's only profile token is the stock consequence
    ("the default profile remains `strict`") — that is
    section attribution, not misattribution, and the shipped
    benchmark document relies on it."""
    named = _named_profiles(paragraph) | set(context)
    if len(named) != 1:
        return []
    (named_profile,) = named
    out = []
    for owner, patterns in PROFILE_FIGURES:
        if owner == named_profile:
            continue
        for pattern in patterns:
            if re.search(pattern, paragraph):
                out.append(
                    f"{rel}: profile attribution — figure "
                    f"(pattern {pattern!r}) is recorded under "
                    f"`{owner}` but the paragraph and its "
                    f"section name only `{named_profile}`: "
                    f"{paragraph[:110]}...")
                break
    return out


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
    # The registered attempt-1 results record carries its
    # own caveats in-line (the FAIL verdict is stated with
    # the figures), so citing it qualifies attempt-1 figures
    # the way citing the baseline qualifies baseline figures.
    r"RESULTS-2026-11-05",
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
    # NFKC first (P5-08c): full-width digits and letters
    # (１.０ for 1.0) fold to their ASCII forms, so a
    # disguised figure meets the same patterns as a plain
    # one. Whitespace is collapsed as before.
    return " ".join(
        unicodedata.normalize("NFKC", paragraph).split())


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
        heading_stack = []
        for paragraph in _paragraphs(text):
            stripped = paragraph.lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_stack = [
                    h for h in heading_stack if h[0] < level]
                heading_stack.append(
                    (level, _named_profiles(paragraph)))
            context = set()
            for _, names in heading_stack:
                context |= names
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
            for m in re.finditer(OF_PATTERN, norm):
                window = norm[max(0, m.start() - FRACTION_WINDOW):
                              m.end() + FRACTION_WINDOW]
                if re.search(FRACTION_CONTEXT, window,
                             re.IGNORECASE):
                    hits.append(OF_PATTERN)
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
            violations.extend(
                attribution_violations(rel, norm, context))
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

    def test_every_phase5_rerun2_variant_fails(self):
        # The second rerun's evasion set (P5-08c, her
        # p5_lint3.py): each phrasing, appended to the README,
        # must fail the lint. Four were already caught before
        # this batch (the recall-1.0, never-misses, recall-is-1
        # and HTML-comment forms — pinned here so they stay
        # caught); six are new: the count-free all-of-set, the
        # "N of N" fraction, the spelled-out percent, the
        # full-width digits, false-positive free and zero
        # misses.
        variants = (
            "Our reviewers reach recall 1.0 on the corpus.",
            "The panel found all seeded defects.",
            "It caught 34 of 34 seeded defects.",
            "The gate never misses a defect.",
            "Measured recall is 1 on the public split.",
            "We reach 100 percent recall.",
            "Recall １.０ on the corpus.",
            "<!-- baseline -->Recall 1.0 on the corpus.",
            "The gate is false-positive free.",
            "Zero misses on the benchmark.",
        )
        for variant in variants:
            texts = load_texts()
            texts["README.md"] += "\n\n" + variant + "\n"
            violations = claim_violations(texts)
            self.assertTrue(
                any("README.md" in v for v in violations),
                f"rerun-2 mutation not caught: {variant!r}")

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

    def test_c1_original_sentence_fails_attribution(self):
        # Defect C1, verbatim: the sentence the README carried
        # until the 2026-11-07 fix. It IS qualified for the
        # claim rule (it cites a record) — the attribution
        # check is what must catch it: every figure in it is
        # `balanced`'s, the only profile it names is `strict`.
        texts = load_texts()
        texts["README.md"] += (
            "\n\nThe default `strict` gate is deliberately "
            "unforgiving. In registered confirmation testing "
            "it caught every seeded defect (recall 1.00) at "
            "0.87 precision — and it blocked 65% of clean "
            "changes. (Registered confirmation record: "
            "bench/BASELINE-V2-2026-11-05.md.)\n")
        violations = claim_violations(texts)
        self.assertTrue(
            any("profile attribution" in v
                and "README.md" in v for v in violations),
            f"C1 sentence not caught: {violations!r}")

    def test_profile_attribution_mutations_fail(self):
        # Each variant states one profile's recorded figure
        # while naming only a different profile — C1's shape,
        # in both directions and across all three profiles.
        variants = (
            "The default `strict` gate blocked 65% of clean "
            "changes in confirmation testing.",
            "Under `strict`, clean-BLOCKED was 22/34 on the "
            "expanded stratum.",
            "The `strict` gate's merged precision was 0.875 "
            "in the registered run.",
            "The `balanced` profile blocked 32 of 34 clean "
            "cases (0.941).",
            "`corroborated` scored clean-BLOCKED 0.647 in "
            "attempt 1.",
            "Under `balanced`, blocking-tier recall was "
            "7/24 = 0.292.",
        )
        for variant in variants:
            texts = load_texts()
            texts["README.md"] += "\n\n" + variant + "\n"
            violations = claim_violations(texts)
            self.assertTrue(
                any("profile attribution" in v
                    and "README.md" in v for v in violations),
                f"attribution mutation not caught: {variant!r}")

    def test_profile_attribution_comparison_passes(self):
        # The legitimate form: a comparison naming both
        # profiles may state both profiles' figures.
        texts = load_texts()
        texts["README.md"] += (
            "\n\nOn the same records, `balanced` blocked "
            "22/34 clean cases (0.647) and `strict` blocked "
            "32/34 (0.941); the paired row is in the "
            "attempt-1 record, bench/generation-v2/"
            "RESULTS-2026-11-05.md.\n")
        violations = claim_violations(texts)
        self.assertFalse(
            any("README.md" in v for v in violations),
            f"comparison paragraph flagged: {violations!r}")

    def test_profile_attribution_needs_a_named_profile(self):
        # Deliberate boundary (see the table's note): a
        # figure stated with NO profile named is the claim
        # rule's problem, not the attribution check's.
        texts = load_texts()
        texts["README.md"] += (
            "\n\nClean-BLOCKED was 0.647 in attempt 1 "
            "(record: bench/generation-v2/"
            "RESULTS-2026-11-05.md).\n")
        violations = claim_violations(texts)
        self.assertFalse(
            any("profile attribution" in v
                and "README.md" in v for v in violations),
            f"unnamed-profile figure flagged: {violations!r}")

    def test_same_paragraph_baseline_reference_qualifies(self):
        texts = load_texts()
        texts["README.md"] = (
            "Recall 34/34 on the public split — see "
            "bench/BASELINE-2026-11-04.md for the caveat.\n")
        self.assertEqual(claim_violations(texts), [])


if __name__ == "__main__":
    unittest.main()
