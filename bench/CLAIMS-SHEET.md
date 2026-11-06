# CodeReview — claims sheet

Companion to `bench/PUBLIC-BENCHMARK.md`. Prepared 2026-11-06.
This sheet governs what may be said externally, today, from the
benchmark record. Every "may say" claim carries its mandatory
caveats with it — a claim quoted without its caveats is not the
claim as cleared here. Governing rule (CodeReview Playbook v2,
Amendment 2): no headline marketing claim ships before the B2
confirmation lands, and until it lands external material may
quote only numbers from completed live / registered runs, stated
with their sets and caveats.

## May say today

- **Corrected precision, baseline 2026-11-04:** "On the public
  split, adjudicated semantic precision was 0.870 finding-level
  and 0.756 merged distinct-defect (blocking tier 0.956 /
  0.906)." Mandatory caveats, attached every time: public split
  only; author-labelled synthetic / injected corpus; ground truth
  enlarged by blind probe-first adjudication of the panel's own
  unmatched findings (100/115 = (24 credited + 64 duplicates +
  12 real-unlabelled) / 115; merged 34/45); panel was OpenAI +
  NVIDIA + DeepSeek with Gemini excluded at preflight; true false
  positives were 7 of 115 findings, plus 4 severity/scope errors
  and 4 undecidable.
  Source: `bench/BASELINE-2026-11-04.md` frontmatter
  `required_caveat` + §6; adjudication summary 2026-11-04.

- **Baseline recall, as bounded:** "The panel matched 24/24
  originally labelled defects on the public split (Wilson 95%
  [0.862, 1.000])." Mandatory caveats: author-labelled corpus the
  team authored; n = 24; quoted with the clean-case figures from
  the same run — clean-case BLOCKED 0.40 (2/5) and any-finding
  0.60 (3/5), n = 5, too small for threshold claims. The 34/34
  post-adjudication form may be stated only with its asymmetry
  caveat attached verbatim in substance: adjudication can only
  add defects the panel found, so it is not an independent recall
  measurement.
  Source: `bench/BASELINE-2026-11-04.md` §6.5, §6.2; adjudication
  summary (Recall denominator effect).

- **Deterministic layer alone, baseline:** recall 0.458, escaped
  0.625, precision 1.000 (11 findings), scored standalone on the
  same public split — stated as the comparison that prices the
  panel's contribution, on that split only.
  Source: `bench/BASELINE-2026-11-04.md` §3.

- **Confirmation attempt 1, as a failed registered run:**
  "In registered confirmation attempt 1 (2026-11-05, profile
  `balanced` / Policy B1), merged blocking precision was 0.875
  and A5 recall was 7-of-7 (1.000; Wilson 95% [0.646, 1.0]) —
  and the run FAILED on the clean stratum: expanded-clean
  BLOCKED was 22/34 = 0.647 scored-only (Wilson 95%
  [0.479, 0.785]; pessimistic view 23/35 = 0.657), against a
  registered ≤ 0.20 threshold." Mandatory attachments: the FAIL
  is part of the claim, never separable from the precision /
  recall figures; 0.647 is attributed to the `balanced` (B1)
  profile on that stratum, and on the identical records `strict`
  BLOCKED 32/34 — B1's 54 demotions rescued 10 clean cases; the
  pre-committed consequence was "don't switch", and the default
  gate profile remains `strict`; 1 unscored case of 44, 0
  degraded, shadow-metered cost $0.294, latency p50 18.5 s /
  p95 57.9 s.
  Source: `bench/generation-v2/RESULTS-2026-11-05.md`.

- **A1 adjudication finding:** "Blind adjudication of the 33
  blocking findings attempt 1 raised on 'clean' cases found
  18 REAL_DEFECT (54.5%), 6 hardening-only, 7 false positives
  and 2 with no majority; 5 executable probes ran and confirmed
  all 5 claims." Mandatory attachments: a majority of the
  supposed false positives were real defects in code that had
  been mislabelled clean; the registered attempt-1 result stands
  as scored on the original labels; labels were amended
  afterwards, dated 2026-11-05, for dev use.
  Source: `bench/analysis-2026-11-05/SUMMARY.md` §A1;
  `bench/expanded-clean/label-amendments-2026-11-05.md`.

- **A1 / A2 / A5 supporting measurements, as analysis results:**
  corroboration cost — 15/31 (48.4%) of labelled defects survive
  a block-only-E0/E1 rule under any-match semantics; probe
  feasibility — 76.1% (105/138) of blocking findings are
  executable claims. Stated as offline analysis findings on the
  consumed sets, not as product performance.
  Source: `bench/analysis-2026-11-05/SUMMARY.md` §A2, §A5.

- **A3 rule sweep, only as a labelled offline / dev result:**
  R2/R3 scored clean-BLOCKED 0.051 (2/39), merged precision
  1.000, any-severity recall 1.000, J 0.949 on the combined
  consumed sets (against R0 strict 0.872 / J 0.128 and R1 B1
  0.590 / J 0.410), with blocking-tier recall 0.484 (15/31)
  stated alongside. Never presented as a live result.
  Source: `bench/analysis-2026-11-05/SUMMARY.md` §A3 + addendum.

- **B2 pilot, only as a clearly-labelled dev-pilot reference in
  technical material:** the pilot may be *referenced* — as an
  unregistered DEV pilot on consumed sets (public split +
  expanded stratum, labels as amended), not a confirmed result —
  with its live row stated as such (clean-BLOCKED 0.125 (5/40)
  as-labelled, label-adjusted 0.080 (2/25) Wilson 95%
  [0.022, 0.25]; any-severity recall 1.000; blocking-tier recall
  0.706; merged precision 1.000; J 0.875; 14/62 degraded, all
  reviewer failure; paired-replay agreement 62/62) and with the
  statement that the registered confirmation has not run
  (registration drafted, unsigned). This is a reference in
  technical material only — see the may-NOT entry below for the
  product-claim prohibition.
  Source: `bench/pilot-b2-2026-11-05/PILOT.md`.

## May NOT say

- **The naive precision 0.209 — never.** Superseded by the
  2026-11-04 adjudicated recount (0.870 / 0.756). It may appear
  only inside a clearly-marked superseded-figures note saying
  do-not-quote, as in `bench/PUBLIC-BENCHMARK.md` §5.
- **Any B2 performance figure as a product claim.** Per Playbook
  Amendment 2, pilot-only figures may not be presented as product
  claims. No claim of the form "B2 achieves / delivers /
  reduces …" until the registered B2 confirmation lands. The
  pilot is referenceable only as a clearly-labelled dev pilot in
  technical material (see above).
- **Any headline marketing claim before the B2 confirmation
  lands** (Playbook Amendment 2). The confirmation's
  registration is drafted and unsigned; no run has started.
- **"PASS proves correctness" — never.** A PASS means no
  actionable issue was found under the checks that ran. It is
  not a correctness guarantee, and no benchmark figure in this
  record changes that.
- **The 0.647 figure attributed to `strict`, or quoted without
  its profile and set.** 0.647 is 22/34 under `balanced` (B1) on
  the expanded-clean stratum in attempt 1; `strict` on the same
  records is 32/34. Quoted without that attribution it is a
  misstatement in either direction, and it is not a marketable
  figure in either direction (Amendment 2).
- **Recall quoted as field accuracy.** Not 24/24, not 34/34, not
  attempt 1's 7-of-7. All recall figures here are measured on
  author-labelled, team-authored sets (public split; A5 n = 7),
  and the 34/34 form additionally carries the adjudication
  asymmetry caveat.
- **Cost claims from the unmetered baseline.** The baseline
  config declares $0 per call: that means unmetered, not free.
  No "free", "$0", or cost-superiority claim may be built on it.
  Attempt 1's $0.294 is a shadow-metered cost of that attempt,
  not a price.
- **Threshold claims from the baseline clean stratum.** n = 5:
  the 0.40 BLOCKED and 0.60 any-finding rates are reported
  baseline facts, not evidence that any threshold is met or
  missed in general.
- **Any figure without its provenance.** Every externally quoted
  number names its run, its set, its profile (where a profile
  applies), and its source document, as in
  `bench/PUBLIC-BENCHMARK.md`.
