# CodeReview benchmark report

Generated: 2026-11-05T00:45:04+00:00 · corpus cases known: 36
**Public report — holdout split excluded.** Holdout cases are the overfit guard; their ids, rows, and scores never appear here.

| Config | Cases | Recall | Escaped-defect rate | Precision | Clean-case FP rate | Cost/verdict | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| panel-baseline-2026-11-04 | 27 | 1.000 | 0.000 | 0.209 | 0.600 | $0.0000 | 19971 ms | 61293 ms |

## panel-baseline-2026-11-04

Defects: 24/24 matched, 0 escaped · findings: 115 (91 false positives) · gates: {"blocked": 24, "pass": 3} · degraded cases: 0

| Case | Split | Category | Gate | Matched | Escaped | FPs | ms |
|---|---|---|---|---:|---:|---:|---:|
| auth-check-removed | public | auth | blocked | 1/1 | 0 | 3 | 18443 |
| clean-add-tests | public | clean | pass | 0/0 | 0 | 2 | 4076 |
| clean-add-timeout-retry | public | clean | blocked | 0/0 | 0 | 2 | 15805 |
| clean-health-guard-fix | public | clean | blocked | 0/0 | 0 | 4 | 65188 |
| clean-parameterized-query | public | clean | pass | 0/0 | 0 | 0 | 7263 |
| clean-refactor-rename | public | clean | pass | 0/0 | 0 | 0 | 3040 |
| command-injection-shell | public | injection | blocked | 1/1 | 0 | 8 | 27606 |
| debug-breakpoint | public | quality | blocked | 1/1 | 0 | 2 | 13891 |
| delete-no-where | public | data-loss | blocked | 1/1 | 0 | 3 | 15188 |
| disabled-test | public | testing | blocked | 1/1 | 0 | 4 | 24300 |
| error-swallow-bare-except | public | error-handling | blocked | 1/1 | 0 | 4 | 20303 |
| eval-user-input | public | injection | blocked | 1/1 | 0 | 5 | 21295 |
| float-money-total | public | correctness | blocked | 1/1 | 0 | 5 | 29549 |
| http-no-timeout | public | reliability | blocked | 1/1 | 0 | 2 | 14715 |
| off-by-one-pagination | public | correctness | blocked | 1/1 | 0 | 3 | 17122 |
| path-traversal-upload | public | security | blocked | 1/1 | 0 | 4 | 24653 |
| payment-amount-dollars-cents | public | payments | blocked | 1/1 | 0 | 2 | 22000 |
| payment-quantity-dropped | public | payments | blocked | 1/1 | 0 | 1 | 7371 |
| plaintext-password-store | public | security | blocked | 1/1 | 0 | 5 | 25881 |
| race-counter-increment | public | concurrency | blocked | 1/1 | 0 | 4 | 22817 |
| real-buggy-alert-flood | public | real | blocked | 3/3 | 0 | 10 | 61293 |
| secret-hardcoded-api-key | public | secrets | blocked | 1/1 | 0 | 2 | 8387 |
| secret-private-key | public | secrets | blocked | 1/1 | 0 | 2 | 24068 |
| sensitive-data-logging | public | security | blocked | 1/1 | 0 | 3 | 15961 |
| sql-injection-fstring | public | injection | blocked | 1/1 | 0 | 4 | 17180 |
| ssrf-fetch | public | security | blocked | 1/1 | 0 | 5 | 28162 |
| unbounded-query | public | performance | blocked | 1/1 | 0 | 2 | 19971 |
