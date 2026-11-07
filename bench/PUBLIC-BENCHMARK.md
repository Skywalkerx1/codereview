# CodeReview — public benchmark

Prepared 2026-11-06; internal artefact packaged for publication;
numbers as of the runs cited. No figure in this document comes
from a run later than 2026-11-05.

## 1. What this measures

CodeReview is a multi-model code review loop: a change is put in
front of independent reviewer models from different providers,
serving different lenses, and a deterministic gate — not a model
vote — decides PASS / BLOCKED / INCONCLUSIVE from the structured
findings. This document measures that whole pipeline (deterministic
scan + panel + gate) against labelled corpora of diffs: how many
labelled defects it catches, how often it blocks a change that
should pass, and how often a finding it raises is, on adjudication,
actually correct. It does not measure field accuracy on real-world
code the team did not author; see §4.

## 2. Methodology

### 2.1 Sets

- **Corpus and public split.** The benchmark corpus is an
  author-labelled set of synthetic / injected-defect diffs plus
  clean controls, authored by the team that built the machinery.
  The 2026-11-04 baseline ran the public split only: 27 cases
  (22 defect cases carrying 24 originally labelled defects, and
  5 clean controls). The holdout split was not run in that
  baseline and is not scored in its numbers.
- **A5 holdout and expanded-clean stratum.** Confirmation
  attempt 1 (2026-11-05) ran a registered set the policy had not
  been tuned on: the A5 private holdout (9 cases; 7 labelled
  defects scored for recall and precision) and an expanded-clean
  stratum (35 clean cases registered; 34 scored, 1 unscored —
  see §3.2). A5 recall is therefore measured on n = 7 defects.
- **Consumed sets and dev reuse.** Attempt 1 consumed the A5 +
  expanded-clean sets once. The offline analyses (§3.3, §3.4) and
  the B2 pilot (§3.5) reuse those consumed sets, plus the public
  split, as dev data for policy design. Results on consumed sets
  are labelled dev / offline wherever they appear; they are not
  confirmation results.
- **Adjudication enlargement, and its asymmetry.** After the
  baseline, all 91 unmatched findings were adjudicated blind to
  seat, probe-first where the claim was executable. Adjudication
  added 10 distinct defects the panel had found but the original
  labels had missed, enlarging public-split ground truth from
  24 to 34 defects. Adjudicating findings can only add defects
  the panel found — it cannot discover a defect no finding
  reported — so a recall figure computed against the enlarged
  truth is not an independent recall measurement. That caveat
  travels with the 34/34 figure in §3.1.

### 2.2 One scoring implementation

There is one scoring implementation. Confirmation scoring wraps
the frozen `bench/scripts/score_confirmation_v2.py` (via
`score_registered.py`); the offline rule sweep was refactored so
its transforms call the product's one evaluation entry point,
`core.evaluate_gate_policy` — grouping included — instead of
re-deriving policy behaviour locally. Replay through that entry
point is the live evaluation path (§6.1 of the expert solution,
as recorded in the addendum to `bench/analysis-2026-11-05/SUMMARY.md`):
after the refactor every headline sweep number reproduced exactly,
and the sweep's sanity checks still pass (R1 reproduces the
registered 22/34 and precision 0.875; R0 reproduces strict 32/34).

Definitions used throughout (see `bench/README.md` for the full
metric definitions):

- **Recall** — matched defects / expected defects. Where a tier
  is named, *any-severity* recall counts a defect matched at any
  severity; *blocking-tier* recall counts only defects matched at
  blocker / major severity.
- **Merged precision** — distinct defects credited / (distinct
  defects + false positives + out-of-scope), with duplicate
  findings on the same defect removed before counting.
- **Clean-case BLOCKED rate** — clean cases whose gate verdict is
  BLOCKED / clean cases. This is the user-visible harm figure.
  It is distinct from the clean-case any-finding rate (clean cases
  drawing ≥ 1 finding), which measures noise, not harm.
- **Informedness J** — J = recall − clean-BLOCKED rate, computed
  on case-level rates (Youden's J as used in these documents).
  Check on one row: the B2 pilot live row reports recall 1.000
  and clean-BLOCKED 0.125, and 1.000 − 0.125 = 0.875, its
  tabulated J. (The worked check uses a dev-pilot row, §3.5;
  measured product figures and their caveat live in
  bench/BASELINE-2026-11-04.md.)

### 2.3 Two views of a registered run

A registered run is reported in two views. The *scored-only* view
scores the records that completed. The *pessimistic* view
re-denominates unscored cases over the full registered universe,
counting an unscored clean case as BLOCKED; precision is unchanged
in that view because an unscored case has no findings. Attempt 1
is reported in both views in §3.2, and its verdict fails under
both.

### 2.4 Intervals

Rates that carry an interval carry a Wilson 95% interval, as
computed in the source documents. Small strata produce wide
intervals; the intervals are part of the result, not decoration.

### 2.5 Trivial baselines

Non-trivial performance is judged against trivial gates. The B2
pilot (§3.5) scores three on the same combined sets: always-pass
(clean-BLOCKED 0.000 / recall 0.000 / J 0.000), always-block
(clean-BLOCKED 1.000 / recall 1.000 / J 0.000), and the
deterministic layer alone (clean-BLOCKED 0.025 / recall 0.265 /
J 0.240). A policy earns its J only above what those score.
(Trivial gates are yardsticks, not results; see the caveat in
§2.1.)

*Provenance: set construction and metric definitions —
`bench/README.md` (Corpus v0; Metrics — exact definitions) and
`bench/BASELINE-2026-11-04.md` §6; adjudication method —
adjudication summary cited in §3.1; scoring implementation —
`bench/generation-v2/RESULTS-2026-11-05.md` (Run identity) and
`bench/analysis-2026-11-05/SUMMARY.md` (Definitions; Addendum —
Step 2+3 single-scoring refactor).*

### 2.6 Pre-registration discipline for attempt 1

Confirmation attempt 1 ran under a pre-registration signed before
the run (registration §1 and Addendum A, signed 2026-11-05 by the
owner and the independent reviewer): thresholds, sets, panel,
gate profile (`balanced`, Policy B1), the two-view reporting rule,
and the unscored-case cap (2) were all fixed before generation.
`verify_registration` exited 0 before the run and was re-verified
after scoring. The registration pre-committed the consequence of
each outcome row in advance; the consequence for the row that
occurred is quoted verbatim in §3.2. A failed threshold is
reported as failed; a new policy requires a new pre-registration.

*Provenance: `bench/generation-v2/RESULTS-2026-11-05.md`
(Run identity; Threshold verdicts; What this means, in the
registration's own terms).*

## 3. Results

### 3.1 Baseline — 2026-11-04, public split

Panel: OpenAI gpt-5.4 (correctness) + NVIDIA
nemotron-3.5-lightning-30b-a3b (operations) + DeepSeek
deepseek-flash (correctness). Gemini was excluded at preflight
(HTTP 429 quota) and never served. Operations rested on a single
family (NVIDIA); correctness had two. The run completed 27/27
cases with 0 degraded cases and 81/81 seat jobs. Latency per
case: p50 20.0 s, p95 61.3 s. Cost was unmetered: the config
declares $0 per call, which means unmetered, not free.

| Metric | Value |
|---|---|
| Recall, originally labelled defects | 24/24 (Wilson 95% [0.862, 1.000]) |
| Recall, after adjudication enlargement | 34/34 — see the asymmetry caveat in §2.1; not an independent recall measurement |
| Corrected precision, adjudicated semantic, finding-level | 0.870 = (24 credited + 64 duplicates + 12 real-unlabelled) / 115 = 100/115 |
| Corrected precision, adjudicated semantic, merged distinct-defect | 0.756 = 34 / (34 + 7 FP + 4 out-of-scope) = 34/45 |
| Corrected precision, blocking tier | 0.956 finding-level / 0.906 merged |
| True false positives | 7 of 115 findings, plus 4 severity/scope errors and 4 undecidable |
| Clean-case BLOCKED rate | 0.40 (2/5) |
| Clean-case any-finding rate | 0.60 (3/5) |
| Deterministic layer alone | recall 0.458, escaped 0.625, precision 1.000 (11 findings) |

The clean stratum is n = 5 — too small for threshold claims; both
clean rates are reported because they are the baseline the later
work reacts to, not because they settle anything. Recall is
reported as 24/24 on the public split with its interval: the
defects are author-labelled on a corpus the team authored and
tuned machinery against. The deterministic-layer row is the
pipeline with the panel removed, scored standalone by subset
rescoring; it is what prices the panel's contribution.
(Baseline: bench/BASELINE-2026-11-04.md.)

*Provenance: `bench/BASELINE-2026-11-04.md` — frontmatter
`required_caveat`, §1 (cases, seat jobs, latency, cost), §2
(panel and preflight), §3 (deterministic-layer row), §6.2
(clean-case metrics), §6.5 (Wilson interval for recall);
adjudication tally and corrected precision —
`adjudication-91-2026-11-04/summary.md` (Class counts; Corrected
semantic precision; Recall denominator effect), in
`~/workspace/goals/reviewloop-multi-model-code-review-product/files/`.*

### 3.2 Confirmation attempt 1 — registered run, 2026-11-05

Profile: `balanced` (Policy B1). Sets: A5 holdout + expanded-clean
stratum, as registered (§2.6). Generation totals: 132 seat-jobs,
131 valid; 1 unscored case of 44 (inside the registered cap of 2);
0 degraded cases, so the run counts as an attempt and is not void.
Latency per case: p50 18.5 s, p95 57.9 s. Shadow-metered cost of
the whole attempt: $0.294.

| Metric | Scored-only view (43 records) | Pessimistic view |
|---|---|---|
| A5 recall (7 labelled defects) | 1.000 (7/7; Wilson 95% [0.646, 1.0]) | 1.000 (of 7) |
| Merged blocking precision (A5) | 0.875 (D=7, U=1; 12 duplicates removed) | 0.875 |
| Expanded-clean BLOCKED | 22/34 = 0.647 (Wilson 95% [0.479, 0.785]) | 23/35 = 0.657 (Wilson 95% [0.492, 0.792]) |
Attempt-1 views of the registered baseline-v2 run — record: bench/BASELINE-V2-2026-11-05.md.

Paired comparison on identical records: under `strict` the same
records BLOCK 32/34 clean cases (0.941); under `balanced`, 22/34.
B1 made 54 demotions and rescued 10 clean cases — a real effect,
and nowhere near the registered ≤ 0.20 clean-BLOCKED threshold
(point estimate, with Wilson upper bound ≤ 0.30). Precision
(≥ 0.50) and recall (≥ 0.95) thresholds passed; both clean-stratum
thresholds failed.

**Verdict: FAIL** — on the clean stratum, under both views.
Pre-committed consequence, verbatim from the registration's
Annex 2: "Clean-BLOCKED fails → Don't switch; consume the
holdout; iterate on a new set." The default gate profile was
therefore not switched; it remains `strict`.

*Provenance: `bench/generation-v2/RESULTS-2026-11-05.md` —
Course of the run; Scores — both views; Threshold verdicts;
Item 7.1 (paired strict vs balanced).*

### 3.3 A1 blind adjudication of attempt 1's clean-stratum blocks — 2026-11-05

Attempt 1 recorded 33 blocking findings on cases labelled clean.
Those 33 were adjudicated blind (A1): panellists did not see which
seat raised a finding, and executable claims were settled by
probes where a probe could run.

| Adjudication outcome | Count (of 33) |
|---|---|
| REAL_DEFECT | 18 (54.5%) |
| HARDENING_ONLY | 6 |
| FALSE_POSITIVE | 7 |
| NO_MAJORITY | 2 |

Five executable probes ran; all 5 claims were confirmed.

Plainly: a majority of the supposed false positives were real
defects in code that had been mislabelled clean. The registered
attempt-1 result in §3.2 stands as scored — it was scored on the
original labels. The labels were amended afterwards, in dated
amendments, for dev use; no registered record or result was
altered.

Two supporting measurements from the same analysis round:

| Measurement | Value |
|---|---|
| A2 corroboration cost — labelled defects surviving a block-only-E0/E1 rule, any-match semantics | 15/31 = 48.4% |
| A5 probe feasibility — blocking findings that are executable claims | 105/138 = 76.1% |

The A2 figure is why corroboration alone is not a cheap fix:
true defects are predominantly single-source at blocking tier, so
a corroboration-only rule loses about half of them at that tier
and verification has to carry the recovery. The A5 figure is the
feasibility basis for prioritising reproducer-backed blocking.

*Provenance: `bench/analysis-2026-11-05/SUMMARY.md` §A1
(verdicts, probes), §A2 (any-match row), §A5 (probe feasibility);
label amendments — `bench/expanded-clean/label-amendments-2026-11-05.md`
(Why; Preservation rule; Coverage: 18 findings across 15 cases).*

### 3.4 A3 offline rule sweep — DEV / offline re-evaluation on consumed sets

This is a dev, offline re-evaluation on consumed sets (A5 +
expanded-clean + public split on its original 24 labels). It is
not a live result and not a confirmation. Rules were evaluated by
replaying stored records through the one scoring implementation
(§2.2). Combined sets: 31 labelled defects, 39 clean cases.

| Rule | Any-severity recall | Merged precision | Clean-BLOCKED | J |
|---|---|---|---|---|
| R0 strict | 1.000 | 0.756 (D31/U10) | 0.872 (34/39) | 0.128 |
| R1 B1 | 1.000 | 0.939 (D31/U2) | 0.590 (23/39) | 0.410 |
| R2 block-only-E0/E1/E2 | 1.000 | 1.000 (D15/U0) | 0.051 (2/39) | 0.949 |
| R3 (= R2 offline) | 1.000 | 1.000 | 0.051 (2/39) | 0.949 |
Offline rule sweep on consumed sets — see the caveat in §2.1.

Two readings must travel with this table. First, recall here is
the any-severity definition: at blocking tier, R2/R3 recall is
0.484 (15/31) under the stored grouping — the gate stops blocking
16 of 31 labelled defects, which remain visible as non-blocking
majors. (Under the live grouping used after the single-scoring
refactor the same diagnostic reads 0.516; the table keeps the
figure as first measured.) Closing that blocking-tier gap is
what R3's cross-family confirmation exists to do, and it cannot
be measured offline — confirmation needs regeneration. Second,
with A1 in hand (§3.3), part of R2's clean-rate gain on the
expanded-clean stratum is demoting findings that blind
adjudication calls real defects in mislabelled cases — another
reason the confirmation step is load-bearing rather than
decorative.

*Provenance: `bench/analysis-2026-11-05/SUMMARY.md` §A3 (rule
table, sanity checks, the two readings) and its Addendum
(single-scoring refactor; blocking-tier recall 0.484 → 0.516
under live grouping).*

### 3.5 B2 dev pilot — unregistered DEV pilot on consumed sets, NOT a confirmed result

The B2 pilot is an unregistered DEV pilot on consumed sets
(public split + expanded stratum, labels as amended 2026-11-05).
It is not a registered run and not a confirmed result. The live
row is the full product pipeline under gate profile
`corroborated`, one live run per case over 62 cases; the paired
rows are the same responses re-evaluated offline through
`core.evaluate_gate_policy`.

| Profile (pilot) | Clean-BLOCKED (combined) | Recall, any-severity | Recall, blocking-tier | Merged precision | J |
|---|---|---|---|---|---|
| live `corroborated` | 0.125 (5/40) | 1.000 | 0.706 | 1.000 | 0.875 |
| paired `strict` | 0.925 (37/40) | 1.000 | 0.971 | 1.000 | 0.075 |
| paired `balanced` | 0.625 (25/40) | 1.000 | 0.941 | 1.000 | 0.375 |

Label-adjusted clean rate, live row: 0.080 (2/25), Wilson 95%
[0.022, 0.25] — the as-labelled rate is 0.125 (5/40); the gap is
cases whose only blockers are findings A1 adjudicated REAL
defects in mislabelled "clean" code. Paired-replay agreement:
62/62. Degraded cases: 14/62, every one with reviewer failure
among its causes — under a registered run those degraded cases
would matter; seat reliability is the pilot's main operational
warning. (Dev-pilot figures — not confirmed results; see
bench/CLAIMS-SHEET.md.)

Trivial baselines on the same combined sets: always-pass
J 0.000; always-block J 0.000; deterministic-only clean-BLOCKED
0.025 / recall 0.265 / J 0.240 (§2.5).

Registered prediction recorded for the confirmation:
clean-BLOCKED 0.080, 95% interval [0.022, 0.25]; any-severity
recall 1.000 [0.898, 1.0]; blocking-tier recall 0.706
[0.538, 0.832]; merged precision 1.000. **The confirmation has
since run (2026-11-06, fresh sealed sets, 88 cases) and FAILED
its primary threshold:** blocking-tier recall measured 0.292
(7/24) against the ≥ 0.60 threshold — below the prediction
interval's lower bound — while clean-BLOCKED passed (6/64 =
0.094, Wilson 95% upper 0.190), any-severity recall held at
1.000 (24/24), and merged blocking precision was 0.778. The
pilot's blocking-tier prediction did not survive contact with
the sealed sets, and the pre-committed consequence stands:
the default profile remains `strict`. Nothing in this section
is a confirmed result, and pilot figures are not product
claims (see `bench/CLAIMS-SHEET.md`).
Source: `bench/confirmation-b2/RESULTS-2026-11-06.md`.

*Provenance: `bench/pilot-b2-2026-11-05/PILOT.md` — header
(provenance, degraded warning), results table, trivial baselines,
live extras (paired-replay agreement), label-adjusted clean rate,
and Prediction for the registered confirmation (§6.3).*

## 4. Limitations

Stated as plainly as the results:

- **Python-only / Python-heavy sets.** The corpus the baseline
  ran on is Python-heavy; the attempt-1 and dev sets are drawn
  from the same programme of authored cases. Nothing here
  measures performance on other languages at scale.
- **Author-labelled ground truth.** The team authored the cases
  the machinery was tuned against. Recall and precision are
  measured against those labels, corrected only by the
  adjudications described in §2.1 and §3.3 — which themselves
  found labels wrong in both directions (missed defects in the
  baseline corpus; "clean" cases carrying real defects).
- **Small strata.** Baseline clean n = 5; A5 recall n = 7
  defects. Intervals at these sizes are wide ([0.646, 1.0] on
  the attempt-1 recall point of 1.000) and no threshold claim
  should rest on the baseline clean stratum.
  (Attempt-1 record: bench/BASELINE-V2-2026-11-05.md.)
- **Adjudication asymmetry on recall.** The 34/34 figure is
  computed against ground truth enlarged by adjudicating the
  panel's own findings; it can only add defects the panel found
  (§2.1). The independent recall measurement is 24/24 on the
  originally labelled defects, with its Wilson interval.
- **Seat reliability.** Gemini was excluded from the baseline
  panel at preflight (HTTP 429 quota) and never served in it.
  In A1 adjudication, NVIDIA returned 14/33 invalid votes and
  Gemini — quota-down — was substituted with second models from
  non-raiser families. In the B2 pilot, 14/62 runs were degraded,
  all with reviewer failure among the causes. Attempt 1 itself
  completed with 0 degraded cases, but only after a mid-run pause
  for an exhausted OpenAI credit balance (diagnosed, refilled,
  resumed from banked records; the pause consumed no attempt).
- **Single-product panel.** Every number here comes from one gate
  implementation and one panel composition (OpenAI + NVIDIA +
  DeepSeek, in that seat order). In the baseline the operations
  lens rested on a single family. No cross-product or
  cross-panel comparison is measured.
- **Cost.** Baseline cost is unmetered (declared $0 per call in
  the config), not free and not measured. The only metered figure
  in this document is attempt 1's shadow-metered $0.294, which
  describes that attempt, not a price.
- **Attempt-1 machinery notes.** The machinery's retry backoff
  during attempt 1 was 1 s-base / 30 s-cap inside the 600 s job
  budget, not the addendum's nominal 20 s-base schedule; the
  binding caps (5 attempts, 600 s/job, 1800 s/case) held
  throughout. Fallback naming in that run: correctness → OpenAI;
  operations had no fallback seat, per Addendum A.

*Provenance: `bench/BASELINE-2026-11-04.md` §4 (caveats) and §6.5;
`bench/generation-v2/RESULTS-2026-11-05.md` (Course of the run;
Machinery notes); `bench/analysis-2026-11-05/SUMMARY.md` §A1
(caveats); `bench/pilot-b2-2026-11-05/PILOT.md` (degraded warning).*

## 5. Superseded figures — do not quote

> **Superseded — do not quote:** the naive one-to-one precision
> figure from the baseline as first published. The scorer's
> one-to-one assignment credited exactly one finding per defect
> and counted every duplicate restatement as a false positive.
> It was superseded on 2026-11-04 by the adjudicated semantic
> recount in §3.1 (0.870 finding-level / 0.756 merged). The
> figure itself is deliberately not reprinted here: the
> standing rule is that it is never quoted, in any context —
> it survives only in the registered baseline record, where
> it stands as history. A reader who meets it in the wild
> should treat any use of it as a current figure as a
> misstatement.

*Provenance: `bench/BASELINE-2026-11-04.md` frontmatter
`required_caveat` and §6.3; adjudication summary cited in §3.1.*

## 6. Reproduction pointers

All paths are relative to the repository root unless absolute.

- Baseline (2026-11-04): `bench/BASELINE-2026-11-04.md`
  (frontmatter caveat, §1–§6); raw records beside it —
  `bench/baseline-2026-11-04-results.jsonl`,
  `bench/baseline-2026-11-04-report.md` / `.json`; panel config
  `bench/configs/panel-baseline-2026-11-04.json`; driver
  `bench/scripts/run_panel_baseline.py`.
- Baseline adjudication (2026-11-04):
  `~/workspace/goals/reviewloop-multi-model-code-review-product/files/adjudication-91-2026-11-04/summary.md`,
  with `adjudication.jsonl` and `fp-corpus.jsonl` in the same
  folder.
- Confirmation attempt 1 (2026-11-05):
  `bench/generation-v2/RESULTS-2026-11-05.md`; records
  `bench/generation-v2/attempt-1.jsonl`,
  `bench/generation-v2/generation-attempt-1.jsonl`,
  `bench/generation-v2/generation-manifest-attempt-1.json`,
  `bench/generation-v2/scoring-output.json`,
  `bench/generation-v2/run-log.txt`; scorer
  `bench/scripts/score_confirmation_v2.py` via
  `bench/generation-v2/score_registered.py`.
- Offline analyses A1–A6 (2026-11-05):
  `bench/analysis-2026-11-05/SUMMARY.md` and its artefacts in the
  same folder (`a1-verdicts.json`, `a3-rule-sweep.json`,
  `a2-corroboration.json`, `a5-probe-feasibility.json`, …);
  label amendments `bench/expanded-clean/label-amendments-2026-11-05.md`.
- B2 dev pilot (2026-11-05): `bench/pilot-b2-2026-11-05/PILOT.md`;
  records `bench/pilot-b2-2026-11-05/pilot-records.jsonl` and
  `bench/pilot-b2-2026-11-05/pilot-results.json` in the same folder.
- B2 registered confirmation (2026-11-06, FAILED):
  `bench/confirmation-b2/RESULTS-2026-11-06.md`; records and
  run logs beside it.
- Metric definitions and corpus description: `bench/README.md`.
- Claims discipline for anything quoted from this document:
  `bench/CLAIMS-SHEET.md`.
