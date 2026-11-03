# Response to External Review 1 — ReviewLoop (2026-11-03)

Reviewer recommendation was "request changes" with two Major findings.
Both were checked against the implementation, **both are correct**, and
both are fixed in **v0.1.1**. No disagreements.

## Finding 1 — Verification cleared findings without checking the evidence

**Accepted.** The prompt demanded evidence, but the result handling
stored status and evidence independently and the gate cleared on
status alone; a bare `{"status":"fixed","evidence":""}` cleared a
blocker.

**Fix (`core.py`):** resolutions are validated before they can clear
anything —
- the status must be in the allowed set (`fixed | still_present |
  invalid | unclear`); anything else is treated as `unclear`;
- a `fixed`/`invalid` claim requires non-empty evidence that shares
  real vocabulary (≥3 content tokens, ≥2 matched, ≥30% overlap) with
  the material under review: the new diff, the test output, the prior
  finding, or the builder's response;
- an unsupported assertion is downgraded to `unclear` — the block
  stays — and the report records the downgrade (`raw_status`,
  `downgraded` fields) so it is visible, not silent.

This is a floor, not a semantic proof: it stops unsupported assertions
and empty evidence, which is the bypass the review identified. Full
semantic verification of evidence remains the reviewers' job in the
round itself.

**Regression tests:** `test_empty_evidence_does_not_clear`,
`test_bogus_status_does_not_clear`.

## Finding 2 — `--strict` could pass a degraded verification round

**Accepted.** The verification gate checked strict-truncation but not
strict-degradation, unlike the review path. With one reviewer down
and the other clearing everything, strict mode still returned PASS.

**Fix:** after the BLOCKED branch, `strict and degraded` now returns
INCONCLUSIVE with the provider failure named in `gate_reasons` —
identical semantics to review rounds.

**Regression test:** `test_strict_degraded_verification_is_inconclusive`
(one clearing reviewer + one failing provider: relaxed mode PASSes,
strict mode is INCONCLUSIVE).

## Verification of the fixes

- Unit suite: **18/18 pass** (was 15).
- Live re-run of the fixture verification round under v0.1.1: still
  PASS — the reviewer's genuine, diff-quoting evidence validates
  cleanly; the new floor does not block honest resolutions.
- The v0.1.1 fix diff itself was run through the loop: PASS
  (NVIDIA operations lens; Gemini degraded on its 429 wall, labelled
  in the report), with the suite green inside the run.

## Not in scope of this round

The two disclosed v0.1.0 items stand as previously noted (contested
concurrency major; deterministic self-reference noise on fixtures —
suppression comments are the first roadmap item). The reviewer
explicitly did not count the disclosed limitation as a finding.
