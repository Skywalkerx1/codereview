# Review notes — CodeReview (prepared for external review, 2026-11-03)

**Update — external review of v0.7.0 (2026-11-04): verdict APPROVE
WITH REQUIRED FIXES. Four findings the internal gate had not caught
— agent seats inheriting every provider API key; a verification
round passing on one surviving reviewer labelled "consensus" (our
own shipped v0.7.0 record did exactly this); agent seats running in
the repo working tree, outside the redaction boundary; cross-kind
seat-name collisions merging into one pool — plus the intake
deadline not ending the process. All verified against the code and
fixed in v0.7.1; gate records in `review-v8/` and
`review-v8-verify/`. The v0.1.0-era reports referenced below as
`review-evidence/` belong to the original self-review package and
are not part of this archive; the gate records included here are
the `review-v6*/`, `review-v7*/` and `review-v8*/` folders and the
`review-*-response-2026-11-03.md` documents.**

**Rename (v0.5.0, 2026-11-03): this project was called ReviewLoop
through v0.4.2 and is now CodeReview. The notes and response
documents in this archive describe the earlier releases under
their original name; the history is unchanged.**

**Update — external Review 3 of v0.4.1: verdict APPROVE, with one
Minor (the staged-mismatch recovery reset the whole Git index).
Verified by reproduction and fixed in v0.4.2: approval commits
are assembled in a temporary Git index, so a refusal never
touches the user's index. Full response in
`review-3-response-2026-11-03.md`.**

**Update — external Review 2 of v0.4.0 returned one Major (a
passing workflow step could commit unrelated working-tree
changes). Verified real by reproduction and fixed in v0.4.1:
clean-tree precondition for fresh steps, byte-exact approval
commits, output dir excluded from the reviewed diff. Full
response in `review-2-response-2026-11-03.md`.**

**Update — external Review 1 returned two Major findings against
v0.1.0 (verification evidence not validated; `--strict` could pass a
degraded verification round). Both were correct, both are fixed in
v0.1.1, and the full response is in `review-1-response-2026-11-03.md`.
The notes below describe the original v0.1.0 self-review.**

This package was reviewed BEFORE packaging by ReviewLoop itself
(the tool reviewing its own source), with Gemini + NVIDIA as the
reviewer panel. Full reports were in `review-evidence/` in the
original v0.1.0 package (not included in this archive — see the
update note at the top).

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

## Fixture evidence (the loop on other code; from the v0.1.0 package, not in this archive)

- `fixture-buggy-blocked.md` — a deliberately buggy
  change (per-violation alert email, f-string DELETE, hardcoded
  password) blocked with 8 findings.
- `fixture-clean-pass.md` — the guarded version of
  the same change passing after a verification round.

## Known limits (also in README)

Diff-only review can false-positive when correctness depends on
code outside the hunk; the verification round is the correction.
Provider outages degrade the panel and are labelled in reports
(Gemini's free tier returned 429/503 through these runs; no run
failed open).
