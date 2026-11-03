# Review notes — ReviewLoop v0.1.0 (prepared for external review, 2026-11-03)

This package was reviewed BEFORE packaging by ReviewLoop itself
(the tool reviewing its own source), with Gemini + NVIDIA as the
reviewer panel. Full reports are in `review-evidence/`.

## What the self-review found, and what happened to each finding

First round (`review-evidence/self-review.md`): gate BLOCKED,
10 findings (7 blocking-severity).

- **Accepted and fixed (2):**
  - Missing edge-case tests → added empty-patch, oversized-patch/
    truncation, and provider-timeout tests. Suite is now 15 tests,
    all passing (`python3 -m unittest discover -s tests`).
  - `shell=True` in the test-command runner → confirmed deliberate
    (operator-supplied commands, never diff-supplied) and documented
    at the call site.
- **Invalidated on rebuttal (6):** the panel's verifying reviewer
  marked them "invalid" with evidence — they were the scanner
  flagging its own rule-definition strings (a "DROP TABLE" finding
  whose evidence is the rule's own title text), its own
  deliberately-buggy test fixtures (fake API key, f-string SQL,
  unguarded sendmail — the fixtures exist so the suite can assert
  the rules fire), a "missing timeout" claim contradicted by the
  code (`timeout=120`), and a "breakpoint present" claim with no
  matching code.
- **Still open (2, stated plainly):**
  1. One scalability major ("unbounded concurrent batches") the
     verifying reviewer kept as still-present. Workers are in fact
     capped at 6 per round; a global wall-clock budget is on the
     roadmap. We did not override the reviewer.
  2. The deterministic layer re-fires on the same fixtures/rule
     strings in every round — by design it cannot be rebutted away
     in v0.1. The fix (suppression comments for fixtures) is the
     first item on the roadmap.

Formal self-review gate: **BLOCKED** — on the two items above, not
on any unexamined finding. Every finding was read, and each was
fixed, invalidated with quoted evidence, or is disclosed here.

## Fixture evidence (the loop on other code)

- `review-evidence/fixture-buggy-blocked.md` — a deliberately buggy
  change (per-violation alert email, f-string DELETE, hardcoded
  password) blocked with 8 findings.
- `review-evidence/fixture-clean-pass.md` — the guarded version of
  the same change passing after a verification round.

## Known limits (also in README)

Diff-only review can false-positive when correctness depends on
code outside the hunk; the verification round is the correction.
Provider outages degrade the panel and are labelled in reports
(Gemini's free tier returned 429/503 through these runs; no run
failed open).
