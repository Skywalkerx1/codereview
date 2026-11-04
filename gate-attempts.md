# Gate attempt ledger — release records for the v0.7.1+v0.7.2 span

Per the clean-record solution (§4.5): non-clean attempts are never
committed *as the release record*, but every attempt is summarized
here so the history is auditable. Range under review:
`3013656..6dae35f`. Requirement (external review of v0.7.1): one
record with gate PASS, degraded=false, both lenses served.

| # | Record | When (ET) | Gemini (correctness) | NVIDIA (operations) | Gate |
|---|--------|-----------|----------------------|---------------------|------|
| 1 | review-v8 | 2026-11-04 ~00:40 | HTTP 429 — free-tier daily quota | ok, clean, 0 findings | PASS, degraded |
| 2 | review-v8b | 2026-11-04 ~00:40 | HTTP 429 — quota | ok, clean, 0 findings | PASS, degraded |
| 3 | review-v9 | 2026-11-04 ~00:47 | HTTP 429 — quota | ok; 1 deterministic minor (POSIX-only test skip, justified) | INCONCLUSIVE (lens coverage) |
| 4 | review-v9c | 2026-11-04 03:20 | error — `GEMINI_API_KEY` not set (scheduled job used the bare CLI; this environment holds only connector credentials) | error — `NVIDIA_API_KEY` not set | INCONCLUSIVE (no reviewer succeeded) |
| 5 | review-v9d | 2026-11-04 03:22 | HTTP 503 — model overloaded (quota had reset) | ok, clean, 0 blockers | INCONCLUSIVE (lens coverage) |
| 6 | review-v9e | 2026-11-04 09:37 | HTTP 429 — free-tier daily quota; OpenAI fallback never fired (its key was not yet registered, so the wired fallback stayed inert) | ok, clean, 0 blockers | INCONCLUSIVE, degraded |
| 7 | review-v11 | 2026-11-04 12:36 | HTTP 429 — quota → OpenAI fallback (family openai, paid) served correctness, 4/4 batches ok | NVIDIA (family nvidia, free), 4/4 batches ok | BLOCKED — span `3013656..09202ca`, tests passed 1/1, degraded=false; 40 findings (26 by-design bench fixtures, 4 real, 9 rebutted, 1 minor); record-verify 7/8 checks — `gate_pass` the only failure |

Traceability for attempt 7: report at `review-v11/codereview-20261104-173626.json`, patch sha256 `36b1943073dd4184ed79bf702b4995a7db5aed83e24876f12dc9a903f5348ae9`, range `3013656..09202ca` (head `09202ca61567e819e9029b97f19a1a1e5bdca32a`). Full per-finding dispositions: `review-v11-dispositions.md`. Attempts 6–7 are history; neither is promoted to the clean record. From attempt 7 on, the span under review is the full current release span, not the v0.7.1+v0.7.2 span above.

Attempts 1–3 are committed with their releases. Attempts 4–5 are
local-only records (review-v9c/, review-v9d/), deliberately
uncommitted. From v0.7.3 on, runs append machine-readable lines
via `--attempts-log`, seats carry family/tier metadata, an OpenAI
fallback seat backs the correctness lens, and eligibility is
decided by `codereview record-verify`, not by reading the report.
