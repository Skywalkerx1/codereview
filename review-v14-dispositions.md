# Review-v14 — dispositions (Phase 0 + Phase 1 of the v14-hold solution)

Record: `review-v14/codereview-20261104-185814.json` (attempt 10,
span `3013656..ddcda92`, gate BLOCKED, record-verify 8/9 —
`gate_pass` the only failure). Governed by the successor issue
report `~/workspace/issue-reports/2026-11-04-codereview-v14-gate-findings.md`
and the owner's solution doc
`~/workspace/user/files/codereview-v14-hold-solution-2026-11-04.md`
(Phases 0 and 1 executed here; Phase 2 machinery and any closing
attempt are out of scope for this round).

**Owner decisions recorded 2026-11-04 (after the attempt, before
this adjudication):** the owner ADOPTED all three recommendations
of the v14-hold solution doc — (1) **Form B** (round-structured
record) is an acceptable closing form; (2) **free-tier =
record-and-attest** (a `record-verify` failure only for a
`private=true` record with a successful free-tier seat — this
settles v13 finding [4], which this round was instructed to leave
untouched; the build is Phase 2 work); (3) **content-addressed
rebuttal precedent is ADOPTED for build** (Phase 2). The five
guard minors below are recorded as standing repeats for this
round and are the first candidates the adopted precedent
mechanism will auto-link once built. The waiver remains unused.

## Phase 0 verdict — truncation RULED OUT

The coverage reconstruction (`review-v14/coverage.md`, built by
re-running the exact batching code path deterministically at
HEAD; patch sha256 recomputed and matching the record):

- Patch offered: **430,910 chars**; post-redaction 430,878 (the
  32-char delta is secret redaction, verified); batch total
  included: **430,878 — difference 0**.
- **7 batches × 2 lenses = 14 reviewer reports, all status ok**
  (correctness via the OpenAI fallback on every batch,
  operations via NVIDIA on every batch). Every one of the 112
  file sections appears in exactly one batch; largest section
  42,151 chars < the 80,000 budget; **omitted hunks: 0**;
  truncated flag false in both the reconstruction and the
  record.
- The texts findings [0]/[1] reason about — the holdout ids in
  `bench/corpus/manifest.json` and the "36 cases" row in
  `bench/README.md` — were present in batch 1, which the raising
  seat (NVIDIA, operations) received and answered.

Per the solution doc's decision gate, truncation is **ruled
out** as a cause: [0]/[1] are **reviewer-quality errors**
(counting/grounding failures over a batch the reviewer did
receive), recorded as such for the benchmark. Phase 2a coverage
machinery is therefore not mandated by Phase 0 evidence —
inclusion was already complete; what failed was arithmetic
over what was shown.

## Dispositions — blocking findings

| # | ID | Sev | Disposition |
|---|----|-----|-------------|
| [0] | `2f3451985487` | blocker | **Rebutted — false positive (Phase 0).** Manifest lists **36 ids = 36 on-disk case directories** (id set == dir set); the 9 holdout cases are *inside* the 36 (27 public + 9 holdout), not additional to it. All 7 ids named in the evidence exist on disk with `case.json` + `diff.patch` and `split: "holdout"` in the manifest. `load_corpus()` loads all 36 without complaint — the loader the finding says "will reject the corpus as-is". The cited line 222 is the manifest's closing brace. Root cause of the claim: the seat counted the holdout entries twice (36 on disk + 9 "in the manifest" = "45"). Full probe output: `review-v14/coverage.md`. |
| [1] | `00569cee995d` | major | **Rebutted — false positive.** Same double-count as [0]. The README's "36 cases: 29 defect cases carrying 31 ground-truth defects, and 7 clean control diffs" is consistent with the shipped corpus (36 total), and that row's text was present in the README section the seat received (batch 1). The cited line 118 is in the "Real baselines" section (about the 8-case subset), not the metrics table. |
| [2] | `e5826ae0d0cb` | major | **Fixed — real in one leg.** Crash leg: already safe since v0.9.1 — probe (exception injected mid-run) left the previous file byte-identical; the abandoned `.tmp` is never loaded (`load_results` reads only `*.jsonl`, `run_bench` reads the exact path). **Provider-failure leg: REAL** — `run_review` absorbs provider failures into degraded records instead of raising, so a `--force` run made while a provider was down completed and swapped: probe replaced a sentinel results file with **27/27 degraded records**. Fix (`bench.py`): under `--force`, if any case in the run came back degraded, the swap is refused — temp file removed, `ValueError` raised (the bench CLI turns it into a clean exit 2 with the reason), previous results byte-intact. Regression tests: `BenchForceDegradedTests` (refusal + healthy-swap control), on top of the v0.9.1 crash test. |
| [3] | `e1185c123236` | major | **Rebutted — by design, no defect.** The `providers_override` path exists only for internal callers (the swarm runner); the public CLI never passes it — every config there gets its own map from `build_config_providers`. Under the override, one panel intentionally serves every named config (configs still differ in name/allow_major/strict), and `run_review` only reads the map (`list(providers.items())`). Probe: two configs ran on one shared dict (27 + 27 records on the real corpus in the Phase 1 probe; fixture-scale in the test) and the dict was **not mutated**. Characterization test: `BenchOverrideSharingTests`. |
| [4] | `56c0cf6a0001` | major | **Rebutted — false positive.** Executable probe: primary seat raises an auth error, fallback serves the correctness lens → the reviewer report carries `provider` = the fallback seat, `status` = **ok**, `error` = **""**, with `fallback_for` and `primary_error` recorded. The v14 record itself is a second witness: all 7 correctness reports show `status: ok` with `fallback_for: gemini`. The code path sets `rec["status"] = "ok"` / `rec["error"] = ""` on any successful (re)run, primary or fallback (`run_review`, post-fallback block). Characterization test: `FallbackReportStatusTests`. |
| [5] | `cbca94f88319` | major | **Rebutted — false positive.** Classification is a partition, not a filter: after `merge_findings`, two complementary comprehensions split the merged list (`fixture_findings` / the rest) — nothing can fall between them. Probe with findings on a fixture path, an inner path, and a product path: 3 in → 1 product + 2 fixture, total preserved; classified findings stay in the record's `fixture_findings` array and the gate reasons state the count (18 in the v14 record). Invariant test: `FixturePartitionTests`. |
| [6] | `4a19a7e9d34b` | major | **Rebutted — false positive; guard test added.** The cited line (core.py:128) is `path_matches`, not subprocess code. The agent execution path is `providers.command_agent`: `proc.communicate(input=..., timeout=timeout)` (providers.py) with the process group killed on timeout; `command_agent` refuses non-positive timeouts at construction (v0.9.2). Every `subprocess.run` in `src/` carries a `timeout=` (120–3600s). Per the solution doc, the guard test was added regardless: `SubprocessTimeoutGuardTests` AST-walks all of `src/` — any `subprocess.run/call/check_*` without a timeout keyword, or a `Popen` whose function lacks a `communicate(timeout=...)`, fails the suite. It passes at HEAD. |
| [7] | `e5fedb444f81` | major | **Rebutted — false positive.** The loop is not unbounded: `_classify_error` caps `max_tries` at 3 (1 for quota/auth/unknown), `_call_with_retry` raises at the cap, and a fallback job is handed only `remaining = _MAX_JOB_ATTEMPTS − primary attempts` (core.py, `run_review`). Probe with always-failing seats (the doc's property test): rate-limit primary spends 3, fallback spends 3, **pair total = 6 = the cap**; a quota job spends 1. Recorded nuance: `_call_and_parse`'s JSON-repair can make up to 3 raw calls inside one tally attempt on a parse failure — but that path ends the job immediately (the ValueError propagates without retry), so it cannot extend a job's life; the cap governs job attempts, the unit the ledger and bench cost accounting count. Characterization test: `RetryPairBudgetTests`. |
| [8] | `dbc3d5d3b94e` | major | **Rebutted — false positive (the doc's "High" guess proved wrong).** (i) `sources` cannot hold a lens name: the only writers are `_normalize_finding` (the serving seat's provider name), the `"deterministic"` literal, and `merge_findings`' copies of those values. (ii) The doc's own fixture, run: a prior finding with `sources: ["correctness"]` and both verifiers confirming "fixed" lands in **unjudged**, gate **INCONCLUSIVE** — the v0.7.1 finder-confirmation rule failing *safe* (nothing clears without the seat that raised it; the gate text tells the operator the way forward), while a provider-named source clears (control: gate PASS, 1 cleared). "Can never clear" misreads a deliberate INCONCLUSIVE as a silent dead end. Characterization tests: `VerificationLensSourceTests`. |
| [9] | `af7e8152da5d` | major | **Fixed — real, narrower than claimed.** Table probe with real provider bodies: Gemini `RESOURCE_EXHAUSTED`, OpenAI `insufficient_quota` / rate-limit / 401, Gemini 403 key-invalid, and the llm_chain message shapes all classified **as intended**. The conflation is real for digit substrings: a 503 body mentioning "4030 tokens" (or a request id "req_4014") classified **(auth, 1)** — a transient failure denied its retries — because `"403"`/`"401"` matched as bare substrings before the transient branch ran. Fix (`core._classify_error`): status codes match as **whole tokens** (`\b…\b`), and the typed quota codes (`resource_exhausted`, `insufficient_quota`) decide the quota class directly, with or without a 429 in the string. Regression tests: `ClassifyErrorTokenTests` (8 real bodies + the substring cases); the v0.7.3 classification tests pass unchanged. Noted residual, outside the cited code and not fixed here: `providers._post_json` discards HTTP error bodies (`"HTTP 429 from <host>"`), so a public-path daily-quota 429 presents as a bare 429 and classifies rate_limit — the classifier can only judge the string it is given; enriching that message has its own trade-offs (provider error bodies would land in records) and is a separate change. |

## Dispositions — minors

| # | ID | Sev | Disposition |
|---|----|-----|-------------|
| [10] | `5b47c709c45f` | minor | **Rebutted in substance; one line added.** The Holdout discipline section already states verbatim "Holdout cases score in the full (internal) report only", and `--split` is documented in the usage examples (`bench/README.md`, `README.md`). Added one cross-reference sentence to the section so the run-side knob is visible from the discipline text itself. |
| [11] | `0d81ded1de5e` | minor | **Standing repeat** — identical finding ID to v13 minor [6] (and v12/v11 before it): the deterministic "test disabled" hit on the POSIX guard line quoted inside `review-v12-dispositions.md`. Rebuttal stands (platform guard, not a disabled test); guard unchanged. First candidate for the adopted content-addressed precedent mechanism (owner decision, 2026-11-04) once built. |
| [12] | `6938d28c87b5` | minor | **Standing repeat** — same ID as v13 [7] / v12 / v11: the guard line inside the filed v9 record JSON. Precedent candidate (see [11]). |
| [13] | `c7f952d7c96f` | minor | **Standing repeat** — same ID as v13 [8] / v12 / v11: the guard line in the v9 record's Markdown. Precedent candidate (see [11]). |
| [14] | `85dda0f810b5` | minor | **Rebutted — by design.** Stripping provider API keys from agent environments is the
...[truncated 2652 chars]
## Fix-diff internal review

The diff of this round's changes (code fixes, tests,
dispositions, ledger row, coverage table) went through the
swarm internal review before commit, per standing practice:
**gate PASS, 0 findings, degraded = false, truncated = false**
— correctness served by the OpenAI fallback (Gemini primary
quota-failed, not retried), operations by NVIDIA, the full
suite passing inside the record (216 tests). Report preserved
with the run's artifacts (`codereview-20261104-222517`).

## Round outcome

All 17 v14 findings dispositioned above (2 fixed, 13 rebutted
with executable evidence — one of those with a guard test and
one with a docs line added — 5 of the rebutted minors recorded
as standing repeats, 1 minor's substance rebutted with a
cross-reference added). Attempt-10 row + traceability committed
in `gate-attempts.md`. Full suite: **216/216**. No version
bump in this round: the fixes ride the Phase 2 release
(v0.9.3). No closing attempt was run (out of scope); the
announcement hold remains on.


## Re-adjudication against master `c4135fe` — 2026-11-05

Ordered by the owner 2026-11-05. The codebase moved enormously
since the Phase 1 dispositions (v0.9.4 → 0.12.1, then Epics K, L,
E, C4, C5 merged the same day), so every disposition was
re-verified against today's code rather than assumed. Method,
per the adopted precedent design: (1) precedent first — a
finding whose cited file blob is unchanged since disposition
(commit `5119998`) stands by precedent; (2) where the cited code
changed, the rebuttal's executable evidence (its
characterization/regression tests) was re-run on master, and
the two fixed defects were additionally re-probed against
their original failure modes. All work was read-only against
master; no code was changed by this round, and no bench set
was run or touched (a registered confirmation run was in
flight throughout).

**Documentation defect found in this file itself:** the
committed Phase 1 text (commit `5119998`, verified byte-level)
contains a literal `...[truncated 2652 chars]` line where the
tail of finding [14]'s disposition and the rows for [15] and
[16] should be — those rows were lost when the Phase 1 text
was written, not by any later edit. The [15]/[16] dispositions
below are reconstructed from the v14 record
(`review-v14/codereview-20261104-185814.json`) and from
`precedents.json`, which carries entries for both IDs
(upserted when the precedent mechanism was built in v0.9.3),
confirming their Phase 1 outcome as standing repeats. [14]'s
substance is recovered from the successor issue report's
Phase 1 addendum ("[14] by-design with the intent comment
added") and verified against the code below.

| # | ID | Phase 1 disposition | Verdict 2026-11-05 | Evidence |
|---|----|-----|-----|-----|
| [0] | `2f3451985487` | Rebutted | **REBUTTAL-HOLDS** | `load_corpus('bench/corpus')` loads all 36 cases (27 public + 9 holdout, unique ids); manifest lists 36 unique ids; every manifest id has `case.json` + `diff.patch` on disk (missing: none). The "holdout ids without artifacts" claim is as false today as at disposition. |
| [1] | `00569cee995d` | Rebutted | **REBUTTAL-HOLDS** | `bench/README.md:25` still states "36 cases: 29 defect cases carrying 31 ground-truth defects, and 7 clean control diffs" — consistent with the corpus verified under [0]. The manifest references 36 ids, not 45. |
| [2] | `e5826ae0d0cb` | Fixed (real, provider-failure leg) | **FIX-INTACT** | The degraded-swap refusal is live in `bench.py`'s `--force` path ("bench --force: N of M cases came back degraded…" → `ValueError`, temp removed, previous results byte-intact). `BenchForceDegradedTests` (refusal + healthy-swap control) green; the v0.9.1 crash-safety force test (`test_v091_fixes.py`) green in the full suite. |
| [3] | `e1185c123236` | Rebutted (by design) | **REBUTTAL-HOLDS** | `BenchOverrideSharingTests` green on current code: two configs sharing one provider map under `providers_override`, map unmutated; the public CLI still builds a per-config map. |
| [4] | `56c0cf6a0001` | Rebutted | **REBUTTAL-HOLDS** | `FallbackReportStatusTests` green: fallback-served reports carry the fallback provider, `status` ok, `error` empty, `fallback_for`/`primary_error` recorded. |
| [5] | `cbca94f88319` | Rebutted | **REBUTTAL-HOLDS** | `FixturePartitionTests` green: fixture/product classification remains a partition of the merged findings (total preserved, classified findings stay in the record). |
| [6] | `4a19a7e9d34b` | Rebutted (+ guard test added) | **REBUTTAL-HOLDS** | `SubprocessTimeoutGuardTests` green — and stronger than at disposition: the AST guard walks the whole of today's much larger `src/`; every `subprocess.run/call/check_*` carries a `timeout=` and every `Popen` path uses `communicate(timeout=...)`. |
| [7] | `e5fedb444f81` | Rebutted | **REBUTTAL-HOLDS** | `RetryPairBudgetTests` green: an always-failing rate-limit pair still spends 3 + 3 = 6 = `_MAX_JOB_ATTEMPTS`; quota/auth/unknown cap at 1 via `_classify_error`'s `max_tries`. |
| [8] | `dbc3d5d3b94e` | Rebutted | **REBUTTAL-HOLDS** | `VerificationLensSourceTests` green: a lens-named source still fails safe to INCONCLUSIVE (nothing clears without its raising seat); a provider-named source clears. |
| [9] | `af7e8152da5d` | Fixed (real, digit-substring conflation) | **FIX-INTACT** | Fresh probe on master: `HTTP 503 … "4030 tokens"` → **transient, 3 tries** (pre-fix this exact shape classified (auth, 1)); `req_4014` → unknown, not auth; `RESOURCE_EXHAUSTED` / `insufficient_quota` → quota; bare 429 → rate_limit; true 401/403 → auth. `ClassifyErrorTokenTests` green in both copies (`tests/test_v093_fixes.py`, `tests/test_v094_probes.py`). |
| [10] | `5b47c709c45f` | Rebutted (+ cross-reference added) | **REBUTTAL-HOLDS** | `bench/README.md` Holdout discipline section intact: "Holdout cases score in the full (internal) report only." plus the Phase 1 cross-reference ("Which split a run executes is a separate knob: `bench run --split public\|holdout\|all` — see the usage examples…"). |
| [11] | `0d81ded1de5e` | Standing repeat | **STANDING-BY-PRECEDENT** | Cited file `review-v12-dispositions.md`: blob `5e466e94…` identical at disposition, in `precedents.json`, and at HEAD (verified via `cli._load_precedents` + `git rev-parse`). |
| [12] | `6938d28c87b5` | Standing repeat | **STANDING-BY-PRECEDENT** | Cited file `review-v9/codereview-20261104-054751.json`: blob `a1342619…` triple-identical as [11]. |
| [13] | `c7f952d7c96f` | Standing repeat | **STANDING-BY-PRECEDENT** | Cited file `review-v9/codereview-20261104-054751.md`: blob `25066390…` triple-identical as [11]. |
| [14] | `85dda0f810b5` | Rebutted (by design; intent comment added) | **REBUTTAL-HOLDS** | `providers.py` `_agent_env` is still allow-list-only by default (keys enter solely via explicit `CODEREVIEW_AGENT_ENV` opt-in), and the Phase 1 intent comment stands verbatim above it in current code, citing this finding: an agent seat never inherits the operator's provider API keys by default. |
| [15] | `ce560a25266e` | Standing repeat (row lost to the in-file truncation; reconstructed) | **STANDING-BY-PRECEDENT** | Per the v14 record: deterministic `disabled-test` hit on `tests/test_external_review_v071.py:62` — the `@unittest.skipUnless(os.name == "posix", "process groups are POSIX")` platform guard, not a disabled test (same rebuttal as [11]–[13]). Cited blob `fe3aad00…` identical at disposition, in `precedents.json`, and at HEAD. |
| [16] | `0aada5c69aab` | Standing repeat (row lost to the in-file truncation; reconstructed) | **STANDING-BY-PRECEDENT** | Per the v14 record: the same guard rule on `tests/test_v091_fixes.py:416` (same POSIX `skipUnless` line in a newer test file). Cited blob `2658fe8e…` identical at disposition, in `precedents.json`, and at HEAD. |

### Round outcome

- Verdicts: **FIX-INTACT 2** ([2], [9]); **REBUTTAL-HOLDS 10**
  ([0], [1], [3], [4], [5], [6], [7], [8], [10], [14]);
  **STANDING-BY-PRECEDENT 5** ([11], [12], [13], [15], [16]);
  **MOOT 0; REAL-NOW 0.** Every Phase 1 disposition still
  holds on master `c4135fe`. Clean sweep — no fix was
  required, so no worktree, gate run, or merge arises from
  this round.
- Characterization/regression evidence re-run for this round:
  the eight disposition test classes in
  `tests/test_v093_fixes.py` plus `ClassifyErrorTokenTests`
  in `tests/test_v094_probes.py` — 16 tests, all green —
  alongside the fresh probes tabulated above.
- Full suite on master `c4135fe`: **1216/1216 OK**.
  `bench/scripts/verify_registration.py`: **PASS** (exit 0).
  Sealed confirmation aggregate sha256 of
  `bench/confirmation-v2/`: `6090ae3b09148a391c161ca1cc9d8606c4c6f4227ff832e61a8d7806c3d861c6`
  — unchanged.
- Nothing in the 17 findings needs an owner decision. The
  one defect this round did surface is documentary, recorded
  above: the Phase 1 minors tail ([14] tail + [15]/[16]
  rows) has been missing from this file since commit
  `5119998` itself; it is reconstructed in this addendum
  rather than silently left absent.
