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

## Empty-content class fix (2026-11-05, branch `empty-class-fix`)

A step-3 follow-up to the forensics, driven by the DeepSeek
soak (`deepseek-soak-2026-11-05.md` in the goal files): the
bench seat wrapper raises `ProviderError(kind="empty")` when
the provider answers with an empty content channel. The
generation layer classified it by message text as "unknown" —
a transport-class failure that latched the seat's per-key
exhausted state, so the product's re-draw never reached the
transport and the report was lost as infrastructure noise
(the voided confirmation's sporadic mode: exactly one DeepSeek
report per attempt on a healthy account; the soak reproduced
the class on 5/24 bench calls, and a raw-API probe measured
the model's reasoning channel at 80–87% of completion tokens
on the affected prompts — the budget is spent where the
wrapper never looks).

- **Fix (`bench/generation.py` only):** a typed
  `ProviderError` with `kind == "empty"` is a CONTENT-class
  failure. `GenerationSeat` records a `content_invalid` event
  with error class `empty` and returns an empty text, handing
  the failure to the product's own retry behaviour
  (`_call_and_parse`'s repair + fresh sample) as the re-draw,
  with the pre-declared per-lens fallback seat as the next
  step. No transport-budget retries, no exhausted latch. The
  raw empty-body transport return stays transport class
  (Addendum A item 4 names the two cases separately); every
  other class mapping is unchanged.
- **Tests:** 4 new in `tests/test_generation.py`
  (`EmptyContentClassTests` + two run-level cases), all
  parent-fail verified against the pre-change tree: empty once
  then valid → served by the seat's own re-draw, recorded as a
  content failure with class `empty`; empty on seat and
  fallback → case unscored for the seat (record status
  `content_failed` — Addendum A item 6 counts a content
  failure no fallback served toward the same unscored cap as
  `unscored-infra`); a typed non-empty provider error still
  takes the transport path.
- **Equivalence check (step-3 gate):** pre-change master and
  this branch ran `run_generation` over the same 2 public
  cases under 6 scripted-transport scenarios. Scenarios with
  no empty outcomes (all-good, content-invalid text, one
  transient 503, persistent 503) are **identical** —
  generation records, attempt records (order-insensitive:
  reviewer-report order is concurrent-execution noise, proven
  by same-tree reruns differing), gates, completion. The two
  empty scenarios diverge **only** in the empty seat's own
  record and exactly as designed: pre-change 1 call, class
  `unknown`, `unscored_infra`, case incomplete (empty-once) —
  post-change the product's 3 draws, class `empty`, served by
  the re-draw; with a fallback declared, final serving is
  identical (fallback serves in both) and only the primary's
  record changes. A live post-change run over 2 public cases
  with the real panel completed both cases (DeepSeek: 3 job
  calls, no empty drawn that run — the class is stochastic,
  ~17–25% per call in the soak; Gemini quota failures were
  served by the declared fallback and recorded as such).
- **Addendum A alignment note:** item 4's failure-class table
  should be aligned to this mapping at signing — its transport
  row currently exemplifies "empty body from the transport
  layer" without distinguishing the seat wrapper's typed
  `kind="empty"` answer (a response that arrived, content
  class). The addendum draft is NOT edited by this branch.

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

## Dedicated bench key (2026-11-05)

Registered runs from now on draw their DeepSeek seat on the
dedicated bench key, registered as the vault connector
`custom.deepseek-bench`, instead of the editorial key
(`custom.deepseek`, which serves the mitbbs editorial drain).
Both keys sit on the same DeepSeek account and share its balance;
the separation buys independent metering and revocation, and the
generation machinery's resumability (first-valid cache, per-case
resume) is what protects a run if the shared balance still dips.

Mechanism: the swarm's `llm_chain.call_deepseek` resolves its
connector at call time via `llm_chain._deepseek_connector()` —
`CODEREVIEW_DEEPSEEK_CONNECTOR` when set, else `custom.deepseek`
(unchanged default for the editorial drain, the internal review
loop, and every other caller). The bench driver entry points
(`bench/scripts/run_panel_baseline.py`, `run_generation_v2.py`,
`run_confirmation_v2.py`) set the variable to
`custom.deepseek-bench` via `os.environ.setdefault`. The switch
is covered by `tests/test_deepseek_connector_switch.py`
(parent-fail verified against the pre-change chain).

Live proof (2026-11-05, branch build): one public case
(`http-no-timeout`) through `run_generation_v2.py` — the
deepseek seat's generation record is `valid`, served by
deepseek (model deepseek-flash, usage metered), and importing
the bench driver resolves `_deepseek_connector()` to
`custom.deepseek-bench` with `deepseek_configured()` true
against that entry, while a no-env process still resolves
`custom.deepseek`.
