# Void-solution findings (§6) — status

Source: `codereview-baseline-v2-void-solution-2026-11-05.md` §6.
Updated 2026-11-05 by the machinery track (branch
`void-sol-track2`); the registration-addendum track owns S2/S3.

| Finding | Status | Where |
|---|---|---|
| **S1** — seat exclusion silently remaps lenses by seat order (product) | **Fixed** on `void-sol-track2` | `core.normalize_seat_lenses` / `core.derive_seat_lenses` / `run_review(seat_lenses=...)`; bench configs carry `seat_lenses` (derived at load when absent, explicit bindings join the config hash); probe + regression tests in `tests/test_seat_lenses.py` (removed-seat panel leaves operations unserved: degraded + INCONCLUSIVE, or fallback-served on the record) |
| **S2** — scorer validated on real holdout records (process) | Open — registration-addendum track | Addendum A disclosure (§4 item 2 of the solution); from now on scorers validate on synthetic or public-split records only |
| **S3** — A5 registration hash not reproducible | Open — registration-addendum track | Per-file SHA-256 manifest + `verify-registration` (§4 item 8) |
| **S4** — cost declared as zero | **Fixed** on `void-sol-track2` | `bench/generation.py`: tokens recorded per job, shadow-priced from `SHADOW_PRICES_USD_PER_1M` (labelled approximate); generation-path attempt records carry metered `cost_usd` |

Machinery (§3) status on the same branch: generation/scoring
separation, record/replay cache, §3.2 failure classes,
pre-declared fallback serving, per-case failure logging and the
failure-vs-feature analysis helper are built and tested
(`tests/test_generation.py`, public-split smoke). The
`unscored-infra` cap and pessimistic-bound scoring (§3.4) belong
to the amended registration's scoring rules — the committed
scorer is unchanged here, per the track's constraints.
