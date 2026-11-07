# Stage-0 P-C falsifier — run log (Spec A + A2)

**Status:** DEV measurement, owner-approved spend 2026-11-07
(~$1.10 expected, hard cap $1.50 shadow). NOT a registered run;
no sealing implications. Design source:
`hidden_files/stage0-pc-persistence-2026-11-07.md` §4 Spec A + A2.

## Pre-stated matching rule (fixed before the first call)

A registered finding **F** (a stored merged finding from
`bench/generation-v2/attempt-1.jsonl`) **recurs** in a fresh
sample **S** of its raising seat X iff at least one finding in S
merges with F under the product merger — applied literally:
`core.merge_findings([F, S_i])` collapses to a single group.
The merger's predicate (`core.merge_findings`): same `file` and
same `category`, and either title-token Jaccard ≥ 0.5, or the
same `line` with title containment (shared tokens / smaller
title) ≥ 0.5.

- Sample findings are the seat's reviewer-level findings:
  `core._normalize_finding(raw, seat, lens="correctness")` over
  the parsed response — exactly what `reviewer_reports` store.
  Downstream gate machinery (grounding, re-ground, cross-family
  confirmation, Tech Lead) is not part of a seat's raise and is
  not applied to samples.
- The sample finding's severity does **not** gate the primary
  count — recurrence means the seat re-raised the claim. A
  major-only sensitivity (sample match must itself be
  blocker/major) is recorded alongside.
- A finding raised by both correctness seats is tested against
  each seat's samples and counts as recurring if it recurs in
  ≥2/3 samples of at least one raising seat (either-seat
  variant); the both-seats variant is reported too.

## Pre-stated decision rule

ρ̂_clean = share of the 32 findings recurring in ≥2/3 samples of
their raising seat. **ρ̂_clean ≥ 0.70 (≥23/32) → P-C DEAD.**
Otherwise P-C lives, with the implied clean-BLOCKED from her
formula at the measured ρ̂ (reference points: 0.334 @ ρ=0.4,
0.221 @ ρ=0.25, 0.517 @ ρ=0.7). ρ̂_defect (A2, 17 findings) is
reported alongside: a low clean ρ̂ with an equally low defect ρ̂
means P-C would spend recall.

## Identity (verified in phase 0, before spending)

- Panel config: `bench/configs/panel-baseline-2026-11-04.json`;
  seats openai → gpt-5.4, deepseek → deepseek-flash
  (llm_chain constants, equal to the stored generation records).
- Params: `run_generation_v2.PARAMS` verbatim (max_tokens 8192,
  temperature 0.1, json_mode, timeout 240); params_hash equals
  the stored records' `67e2b57b…` for both correctness seats.
- Prompts: rebuilt through the product's own `core.run_review`
  prompt construction on the registered context string; the
  phase-0 spy capture's prompt hash must appear in the stored
  valid generation record's `prompt_hashes` for every
  (case, seat) — see `identity-check.json`.
- DeepSeek transport resolves to `custom.deepseek-bench`
  (`CODEREVIEW_DEEPSEEK_CONNECTOR`, as the registered runs).

## Sampling protocol

Fresh k=3 per (case, seat): 31 cases × 2 seats × 3 = 186 draws.
A draw = `core._call_and_parse` over a cache-free
`GenerationSeat` (the product's own sample production, including
its parse-repair + fresh redraw). A draw that fails outright is
retried with a fresh seat up to 2 more times; only an all-failed
draw is recorded invalid, and invalid draws never count as
non-recurrence. Spend is shadow-metered per raw call with
`bench/generation.py`'s price table; no new draw starts if
spent + $0.045 (worst-case draw) would exceed the $1.50 cap.

## Execution record

- **Phase 0 (identity), 2026-11-07:** populations reproduced
  exactly (clean 22 cases / 32 findings; defect 9 cases / 17
  correctness-raised findings; per-case distribution 12×1, 9×2,
  1×3 — all matching the offline analysis). Prompt identity
  verified for all 31 cases × 2 seats. Two cases
  (`secret-aws-key`, `xc-password-hash-verify`) failed the check
  under current master: `redact_secrets` rendering drifted after
  the registered run (P3-03 `fb478be`, L8 `c7b26b7`). Rebuilt
  under the registered run's code state (master `a808008`,
  worktree), every prompt hash matches the stored records;
  29/31 prompts are byte-identical across the two code states,
  the 2 drifted ones differ only inside the redaction spans.
  `prompts.json` (sampling input) is the a808008 build;
  draw/parse/normalise/match mechanics are the current product
  (69d1c65). See `identity-check.json` (failures kept on record
  with the resolution).
- **Phase 1 (sampling):** 186/186 draws valid, 0 invalid,
  0 cap-skipped; 234 raw transport calls; shadow spend
  **$0.9060** (cap $1.50). Raw outputs in `raw/`.
- **Phase 2 (scoring):** ρ̂_clean = **7/32 = 0.219**,
  ρ̂_defect = **10/17 = 0.588** — **P-C LIVES** under the
  pre-stated rule (kill line 0.70). Full numbers, the case-level
  simulation and the recall price (2 of 8 defect cases) in
  `RESULTS-2026-11-07.md`; per-finding detail in
  `recurrence-table.json`.
