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

## Verification-round fixes (2026-11-05, same branch)

The internal review's verification round BLOCKED the branch on
one major + four minors, all in
`bench/scripts/run_generation_v2.py`. All five are fixed;
tests in `tests/test_generation_driver.py` (15 of 16 fail on
the pre-fix branch; the 16th is a regression pin for behaviour
the parent already had).

- **Major — registered-set guard covered only `holdout`.**
  The driver documented the A5 holdout AND the expanded-clean
  stratum as registered-only but refused only `holdout`. (The
  expanded stratum was in fact unreachable — the driver loads
  only `bench/corpus`, whose splits are public/holdout — but
  the guard now makes that irrelevant.) `registered_guard`
  refuses EVERY non-public split by name, before config load,
  preflight, or any seat call, unless
  `CODEREVIEW_REGISTERED_RUN=1`. A future loader change cannot
  silently open a registered set.
- **Minor 1 — fallbacks could name seats outside the panel.**
  `validate_fallbacks` at driver entry (and strict resolution
  in `generation.run_generation`, which previously dropped
  unknown seats silently) raises on an unknown lens or a
  fallback seat that is not a declared panel seat.
- **Minor 2 — CLI `--fallbacks` were outside the run's
  identity.** The effective fallbacks now join the run
  identity: the generation manifest records `fallbacks` and a
  `run_identity_sha256` over (config hash, seat_lenses
  binding, fallbacks), and a resume whose fallbacks differ is
  a hard error, like a config-hash mismatch. They were not
  folded into `bench._config_sha` itself: that hash keys
  stored bench records across drivers, and moving it would
  orphan them (the same reasoning `_config_sha` documents for
  derived bindings). Per-case records already attest the
  serving that actually happened (`served_by`/`fallback_for`).
- **Minors 3+4 — fallbacks were not cross-validated against
  the explicit `seat_lenses` binding.** At driver entry, under
  an explicit binding, a fallback naming for a lens a seat the
  binding does not bind to that lens — while the lens is bound
  to other seat(s) — raises with a clear message: a fallback
  may not reassign a lens the binding gives to a different
  seat (the S1 remap). A fallback for a lens the binding
  leaves unbound is allowed (it covers an otherwise unserved
  lens), and Addendum A's declared correctness fallbacks (the
  two correctness seats are each other's fallback) validate
  clean, since both are bound to the lens.

## Budget model (reconciled)

One coherent two-level model, stated identically in
`bench/generation.py`'s docstring and here (Addendum A's
retry-budget item states the per-case level; it is not edited
by this branch):

- per-JOB: one (seat, prompt) job retries transport failures
  inside a **600 s** wall-clock budget and the per-job attempt
  cap (`GenerationSeat`, `JOB_WALL_CLOCK_BUDGET_S`);
- per-CASE: all of a case's seat jobs, retries and waits share
  a **1,800 s (30-minute)** budget (`run_generation`'s
  `case_budget_s`, `CASE_WALL_CLOCK_BUDGET_S`), enforced by
  stamping each seat with a case deadline on its own clock for
  the duration of the case's `run_review` call. A job that
  hits the case deadline exhausts like a job that hits its own
  budget and the seat's case record lands `unscored-infra`.
  Deadline exhaustion is deliberately not latched into the
  per-key exhausted state: a later case stamps a fresh
  deadline, and within the case the deadline check itself
  fails re-entry fast before any transport call.
