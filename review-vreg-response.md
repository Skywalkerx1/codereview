# Builder response — review-vreg round 1

One major raised (nvidia, operations lens; the finding was also
flagged UNGROUNDED by the gate itself — its evidence quote could not
be re-grounded). Rebutted as **invalid** below; no code changed.

## Finding: "Logic inversion in superseded/FAIL determination for body hash check 6"

**Claim.** The post-fill row reports SUPERSEDED when `body_hash`
equals the current post-append hash; the reviewer says it should
report FAIL in that case and SUPERSEDED otherwise, because "the
post-fill state is now superseded and the current state is the
post-append hash."

**Why the claim is self-contradictory.** SUPERSEDED on the old row
is a statement about the OLD expectation, exactly as in this file's
check 3: the A5 registered set-hash row reports SUPERSEDED because
that registered state has been replaced by its successor (the
item-8 per-file manifest). A registered state is superseded
precisely when the artefact has moved on to the successor state —
not when it hasn't. The post-fill body state was superseded BY the
§3 Addendum A append; it is therefore SUPERSEDED exactly in the
state where the body recomputes to the post-append hash. The
reviewer's own sentence ("the post-fill state is now superseded")
describes that very state, then assigns it FAIL.

**Truth table of the shipped code** (rows: post-fill row, then the
companion current-state row, which checks
`REGISTRATION_BODY_SHA256_CURRENT` by strict equality):

| body state | post-fill row | current row | exit |
|---|---|---|---|
| post-append (authorised, live) | SUPERSEDED | PASS | 0 |
| post-fill (append lost/reverted) | FAIL | FAIL | 1 |
| anything else (tampered) | FAIL | FAIL | 1 |

Exit 0 is reachable in exactly one body state — the authorised
one. Nothing was weakened.

**Empirical controls (run by the builder, this branch).** Two
tampered copies of the live registration via `--registration`:
(a) one byte flipped in the body → both body rows FAIL, exit 1;
(b) one unauthorised line inserted above the FOOTER-HASH line →
both body rows FAIL, exit 1. The live document itself → SUPERSEDED
+ PASS, exit 0.

**What the proposed "fix" would do.** Invert the condition and
the authorised state reports FAIL (exit 1 forever — Addendum A
item 10, which requires this script to exit 0 before any run under
the addendum, could never be satisfied), while a tampered body
would be labelled SUPERSEDED. The proposal is the inversion.

**Requested disposition:** major resolved `invalid`.
