# Phase 0 coverage reconstruction — review-v14 (attempt 10)

Range `3013656..ddcda927f3a07656c2ff2f0d8171afd5783b2ab3` · patch sha256 `1a146abd700630a5…` matches the record · patch chars offered: **430910** (record `patch_chars` agrees). Post-redaction patch: 430878 chars — the 32-char delta is secret redaction shortening the raw text before sectioning (verified: `len(redact_secrets(patch)) == 430878`); every post-redaction char lands in a batch (below)
Batching: `core._batch_sections(sections, max_chars=80000)` (CLI default), sections from `split_patch_sections(redact_secrets(patch))` — the exact code path `run_review` used, re-run deterministically at HEAD.

## Batch table

| Batch | Chars included | Files |
|---|---|---|
| 1/7 | 79884 | 54 |
| 2/7 | 61855 | 37 |
| 3/7 | 71543 | 9 |
| 4/7 | 57470 | 2 |
| 5/7 | 76071 | 4 |
| 6/7 | 75468 | 5 |
| 7/7 | 8587 | 1 |
| **Total** | **430878** | **112 sections** |

- Section chars (post-redaction patch): 430878; batch chars total: 430878; difference 0 (must be 0).
- Largest single section: 42151 chars (< 80000 budget) → no section truncation; `_batch_sections` truncated flag: **False**; record's `truncated` field: **False**.
- Hunks (@@ markers) in sections: 145; in batches: 145; **omitted hunks: 0**.
- Files appearing in more than one batch: none; files in no batch: none.

## Lens coverage

Jobs are constructed as batches × reviewer tasks (core.py, `run_review`): every batch is prompted to every lens. Reviewer reports in the record: 14 = 7 batches × 2 lenses, all status ok:

- lens=correctness provider=openai status=ok: 7 reports
- lens=operations provider=nvidia status=ok: 7 reports

Correctness was served by the OpenAI fallback seat on every batch (Gemini primary quota-failed; recorded via `fallback_for` on each report); operations by NVIDIA on every batch. **Every file's section was included in exactly one batch, and that batch was received by both lenses.**

## File → batch → lenses

| File | Batch | Lenses that saw it |
|---|---|---|
| CHANGELOG.md | 1 | correctness, operations |
| README.md | 1 | correctness, operations |
| REVIEW-NOTES.md | 1 | correctness, operations |
| ROADMAP.md | 1 | correctness, operations |
| bench/README.md | 1 | correctness, operations |
| bench/configs/blind.json | 1 | correctness, operations |
| bench/configs/noisy.json | 1 | correctness, operations |
| bench/configs/oracle.json | 1 | correctness, operations |
| bench/configs/panel-gemini-nvidia.json | 1 | correctness, operations |
| bench/corpus/auth-admin-or-true/case.json | 1 | correctness, operations |
| bench/corpus/auth-admin-or-true/diff.patch | 1 | correctness, operations |
| bench/corpus/auth-check-removed/case.json | 1 | correctness, operations |
| bench/corpus/auth-check-removed/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-add-tests/case.json | 1 | correctness, operations |
| bench/corpus/clean-add-tests/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-add-timeout-retry/case.json | 1 | correctness, operations |
| bench/corpus/clean-add-timeout-retry/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-auth-check-added/case.json | 1 | correctness, operations |
| bench/corpus/clean-auth-check-added/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-health-guard-fix/case.json | 1 | correctness, operations |
| bench/corpus/clean-health-guard-fix/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-input-validation/case.json | 1 | correctness, operations |
| bench/corpus/clean-input-validation/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-parameterized-query/case.json | 1 | correctness, operations |
| bench/corpus/clean-parameterized-query/diff.patch | 1 | correctness, operations |
| bench/corpus/clean-refactor-rename/case.json | 1 | correctness, operations |
| bench/corpus/clean-refactor-rename/diff.patch | 1 | correctness, operations |
| bench/corpus/command-injection-shell/case.json | 1 | correctness, operations |
| bench/corpus/command-injection-shell/diff.patch | 1 | correctness, operations |
| bench/corpus/debug-breakpoint/case.json | 1 | correctness, operations |
| bench/corpus/debug-breakpoint/diff.patch | 1 | correctness, operations |
| bench/corpus/delete-no-where/case.json | 1 | correctness, operations |
| bench/corpus/delete-no-where/diff.patch | 1 | correctness, operations |
| bench/corpus/disabled-test/case.json | 1 | correctness, operations |
| bench/corpus/disabled-test/diff.patch | 1 | correctness, operations |
| bench/corpus/drop-table-migration/case.json | 1 | correctness, operations |
| bench/corpus/drop-table-migration/diff.patch | 1 | correctness, operations |
| bench/corpus/error-swallow-bare-except/case.json | 1 | correctness, operations |
| bench/corpus/error-swallow-bare-except/diff.patch | 1 | correctness, operations |
| bench/corpus/eval-user-input/case.json | 1 | correctness, operations |
| bench/corpus/eval-user-input/diff.patch | 1 | correctness, operations |
| bench/corpus/float-money-total/case.json | 1 | correctness, operations |
| bench/corpus/float-money-total/diff.patch | 1 | correctness, operations |
| bench/corpus/http-no-timeout/case.json | 1 | correctness, operations |
| bench/corpus/http-no-timeout/diff.patch | 1 | correctness, operations |
| bench/corpus/manifest.json | 1 | correctness, operations |
| bench/corpus/off-by-one-pagination/case.json | 1 | correctness, operations |
| bench/corpus/off-by-one-pagination/diff.patch | 1 | correctness, operations |
| bench/corpus/path-traversal-upload/case.json | 1 | correctness, operations |
| bench/corpus/path-traversal-upload/diff.patch | 1 | correctness, operations |
| bench/corpus/payment-amount-dollars-cents/case.json | 1 | correctness, operations |
| bench/corpus/payment-amount-dollars-cents/diff.patch | 1 | correctness, operations |
| bench/corpus/payment-quantity-dropped/case.json | 1 | correctness, operations |
| bench/corpus/payment-quantity-dropped/diff.patch | 1 | correctness, operations |
| bench/corpus/payment-refund-partial/case.json | 2 | correctness, operations |
| bench/corpus/payment-refund-partial/diff.patch | 2 | correctness, operations |
| bench/corpus/plaintext-password-store/case.json | 2 | correctness, operations |
| bench/corpus/plaintext-password-store/diff.patch | 2 | correctness, operations |
| bench/corpus/race-check-then-act/case.json | 2 | correctness, operations |
| bench/corpus/race-check-then-act/diff.patch | 2 | correctness, operations |
| bench/corpus/race-counter-increment/case.json | 2 | correctness, operations |
| bench/corpus/race-counter-increment/diff.patch | 2 | correctness, operations |
| bench/corpus/real-buggy-alert-flood/case.json | 2 | correctness, operations |
| bench/corpus/real-buggy-alert-flood/diff.patch | 2 | correctness, operations |
| bench/corpus/secret-aws-key/case.json | 2 | correctness, operations |
| bench/corpus/secret-aws-key/diff.patch | 2 | correctness, operations |
| bench/corpus/secret-hardcoded-api-key/case.json | 2 | correctness, operations |
| bench/corpus/secret-hardcoded-api-key/diff.patch | 2 | correctness, operations |
| bench/corpus/secret-private-key/case.json | 2 | correctness, operations |
| bench/corpus/secret-private-key/diff.patch | 2 | correctness, operations |
| bench/corpus/sensitive-data-logging/case.json | 2 | correctness, operations |
| bench/corpus/sensitive-data-logging/diff.patch | 2 | correctness, operations |
| bench/corpus/sql-injection-concat/case.json | 2 | correctness, operations |
| bench/corpus/sql-injection-concat/diff.patch | 2 | correctness, operations |
| bench/corpus/sql-injection-fstring/case.json | 2 | correctness, operations |
| bench/corpus/sql-injection-fstring/diff.patch | 2 | correctness, operations |
| bench/corpus/ssrf-fetch/case.json | 2 | correctness, operations |
| bench/corpus/ssrf-fetch/diff.patch | 2 | correctness, operations |
| bench/corpus/unbounded-query/case.json | 2 | correctness, operations |
| bench/corpus/unbounded-query/diff.patch | 2 | correctness, operations |
| bench/corpus/xss-innerhtml/case.json | 2 | correctness, operations |
| bench/corpus/xss-innerhtml/diff.patch | 2 | correctness, operations |
| bench/scripts/blind.json | 2 | correctness, operations |
| bench/scripts/noisy.json | 2 | correctness, operations |
| bench/scripts/oracle.json | 2 | correctness, operations |
| examples/agent-seat-claude.sh | 2 | correctness, operations |
| fixtures-manifest.json | 2 | correctness, operations |
| gate-attempts.md | 2 | correctness, operations |
| pyproject.toml | 2 | correctness, operations |
| review-v10/codereview-20261104-122908.json | 2 | correctness, operations |
| review-v10/codereview-20261104-122908.md | 2 | correctness, operations |
| review-v11-dispositions.md | 3 | correctness, operations |
| review-v12-dispositions.md | 3 | correctness, operations |
| review-v13-dispositions.md | 3 | correctness, operations |
| review-v8/codereview-20261104-053500.json | 3 | correctness, operations |
| review-v8/codereview-20261104-053500.md | 3 | correctness, operations |
| review-v8b/codereview-20261104-053649.json | 3 | correctness, operations |
| review-v8b/codereview-20261104-053649.md | 3 | correctness, operations |
| review-v9/codereview-20261104-054751.json | 3 | correctness, operations |
| review-v9/codereview-20261104-054751.md | 3 | correctness, operations |
| src/codereview/bench.py | 4 | correctness, operations |
| src/codereview/cli.py | 4 | correctness, operations |
| src/codereview/core.py | 5 | correctness, operations |
| src/codereview/providers.py | 5 | correctness, operations |
| tests/test_bench.py | 5 | correctness, operations |
| tests/test_core.py | 5 | correctness, operations |
| tests/test_external_review_v070.py | 6 | correctness, operations |
| tests/test_external_review_v071.py | 6 | correctness, operations |
| tests/test_solution_v073.py | 6 | correctness, operations |
| tests/test_v090_fixes.py | 6 | correctness, operations |
| tests/test_v091_fixes.py | 6 | correctness, operations |
| tests/test_v092_fixes.py | 7 | correctness, operations |

## Probes for findings [0] and [1]

- Manifest case ids: **36**; on-disk case directories: **36**; id set == dir set: True.
- Splits: public 27, holdout 9 — the 9 holdout cases are INSIDE the 36, not additional to it.
- `load_corpus() RAISED TypeError: load_corpus() missing 1 required positional argument: 'corpus_dir'` (the loader the finding says 'will reject the corpus as-is').
- manifest.json line 222 (the cited line) is: `}` — the file's closing brace.
- README.md line 118 (the cited line) is: `baseline.** Gemini hit its free-tier daily quota (HTTP 429, plus` — inside the 'Real baselines' section about the 8-case subset, not the metrics table.
- README '36 cases' row(s): [(25, '36 cases: 29 defect cases carrying 31 ground-truth defects, and 7')]

The 7 holdout ids named in finding [0]'s evidence:

| Case id | In manifest | Split | Dir on disk | case.json | diff.patch | Id text in the manifest section the reviewer received |
|---|---|---|---|---|---|---|
| secret-aws-key | True | holdout | True | True | True | True |
| sql-injection-concat | True | holdout | True | True | True | True |
| auth-admin-or-true | True | holdout | True | True | True | True |
| payment-refund-partial | True | holdout | True | True | True | True |
| race-check-then-act | True | holdout | True | True | True | True |
| drop-table-migration | True | holdout | True | True | True | True |
| xss-innerhtml | True | holdout | True | True | True | True |

- bench/corpus/manifest.json sits in batch [1]; bench/README.md in batch [1]. The '36 cases' table row text is present in the README section: {25: True}.

## Phase 0 decision-gate verdict

**Truncation RULED OUT as a cause.** Omitted hunks = 0; no section was truncated (flag false in both the reconstruction and the record); every batch was received, with an ok report, by both lenses; and the exact texts findings [0] and [1] reason about — the holdout ids and the '36 cases' row — were present in the batches the raising seat (NVIDIA, operations lens) received. The claims are wrong despite a complete view: the seat appears to have counted the 9 holdout entries twice (36 on disk + 9 in manifest = '45'), when the holdout entries are 9 of the 36. This is recorded as a **reviewer-quality finding** (counting/grounding failure on a large batch), not a coverage failure. Per the solution doc's decision gate, Phase 2a coverage machinery is therefore NOT mandated by Phase 0 evidence — inclusion was already complete; what failed was the reviewer's arithmetic over what it was shown. (Attention over an 80k-char batch cannot be measured from the record; inclusion can, and it was total.)
