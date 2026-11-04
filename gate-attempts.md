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
| 6 | review-v9e | 2026-11-04 ~09:37 | scheduled (two-seat panel) | scheduled | pending |

Attempts 1–3 are committed with their releases. Attempts 4–5 are
local-only records (review-v9c/, review-v9d/), deliberately
uncommitted. From v0.7.3 on, runs append machine-readable lines
via `--attempts-log`, seats carry family/tier metadata, an OpenAI
fallback seat backs the correctness lens, and eligibility is
decided by `codereview record-verify`, not by reading the report.
