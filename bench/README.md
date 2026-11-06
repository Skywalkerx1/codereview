# CodeReview benchmark (Epic A)

The benchmark is how CodeReview proves its one promise — *a
verifiable verdict on AI-written code* — with numbers instead of
adjectives. It runs named review configurations over a labelled
corpus of diffs and scores each configuration against ground truth.

```bash
# deterministic, zero provider calls (scripted replay seats):
codereview bench run --config oracle --config blind --config noisy
codereview bench report                 # full report (MD + JSON with --out-dir)
codereview bench report --public        # public report: holdout excluded

# a real panel (needs provider credentials in the environment):
codereview bench run --config panel-gemini-nvidia --split public
```

Runs are resumable: results append to `bench-out/<config>.jsonl`
and already-recorded cases are skipped (use `--force` to redo a
config). `bench report --max-escaped-rate 0.2` exits 1 when any
configuration regresses past the threshold, for CI.

## Corpus v0

36 cases: 29 defect cases carrying 31 ground-truth defects, and 7
clean control diffs. 27 cases are public, 9 are holdout.

| Category | Cases | Notes |
|---|---:|---|
| secrets | 3 | hardcoded key, private key, AWS key |
| injection | 5 | SQL (f-string + concatenation), shell, eval, SSRF-adjacent fetch |
| auth | 3 | removed permission check, `or True` bypass, + 1 clean control |
| payments | 4 | dollars-vs-cents, dropped quantity, partial-refund |
| concurrency | 3 | read-modify-write counter, check-then-act |
| data-loss | 3 | DELETE without WHERE, table-dropping migration |
| security (misc) | 5 | path traversal, plaintext password, password logging, XSS |
| reliability / performance / quality | 6 | bare except, no timeout, unbounded query, float money, off-by-one, breakpoint, skipped test |
| real | 1 | the demo health-checker change (3 defects), converted from this repo's own stored run artifacts |
| clean | 7 | parameterized-query fix, timeout+retry, rename, added tests, alert-guard fix (this repo's `examples/clean_change.patch`), auth check added, input validation |

Sources: every case is either authored for this corpus (defect
injection; file headers in `case.json` say so) or converted from
this repository's own examples/demo records. All are MIT-licensed
with the repo; no third-party code is included. Case format:
`<id>/case.json` + `<id>/diff.patch`, indexed by `manifest.json`
(the loader refuses a corpus whose manifest and directories
disagree).

The deterministic scan alone catches 13 of the 41 defects
(pattern-shaped: secrets, injection strings, destructive SQL,
eval, skips). The other 28 need judgement — removed auth checks,
unit-of-money bugs, races, swallowed errors. That split is the
point of the benchmark: it prices what the model panel adds over
the free deterministic layer. (Corpus total was 31 until
2026-11-04, when semantic adjudication of the first baseline's
unmatched findings added 10 genuine defects the panel had found
but the original labels had missed; the additions are marked
`adjudication_added` in each `case.json`. Scores quoted from the
2026-11-04 baseline were computed against the original 31.)

**Growth path to 50–100 cases** (A2's full target): (1) convert
more of our own stored run records — every public miss becomes a
corpus case within 48 hours, per the roadmap; (2) CVE-style fix
pairs (vulnerable diff + its real fix as a clean control) written
from public advisories, keeping only facts and our own code;
(3) more languages (the corpus is Python-heavy today, with one JS
case); (4) multi-file diffs and migration changes. Holdout grows
in proportion and is never published. **Owner:** the bench
maintainer (whoever ships the current release). **Timeline:**
at least 50 cases by the next minor release after 0.9.0, 100 by
the release after that; the 48-hour public-miss rule in (1)
applies continuously, not at release time.

## Metrics — exact definitions

A reported finding **matches** an expected defect when they name
the same file AND either the line numbers are within 3, or (lines
missing/far) the finding's title shares ≥ 0.3 Jaccard word-token
overlap with the expected title/keywords. Severity and category
are not required to match (ground truth is severity + location);
a category mismatch is recorded. Matching is greedy, worst
severity first, one-to-one both ways.

- **Recall** — matched defects / expected defects.
- **Escaped-defect rate** — defects whose matching finding (if
  any) carries no gate-blocking severity (blocker/major), over
  expected defects. A defect reported only as a minor still
  escapes: the default gate would have shipped the change. This
  is the headline metric.
- **Precision** — matched findings / all reported findings.
- **Clean-case BLOCKED rate** — clean cases whose gate verdict is
  blocked / clean cases. The user-visible harm figure.
- **Clean-case any-finding rate** — clean cases with ≥ 1 finding /
  clean cases (the harness's `clean_fp_rate` field). On a clean
  case every finding is a false positive; this rate measures
  noise, not harm — do not quote it as the blocked rate.
- **Clean-case blocking-finding count** — blocker/major findings
  on clean cases, reported per case.
- **Cost per verdict** — summed seat attempts × the config's
  `cost_per_call_usd`, over cases run. Scripted seats cost 0;
  real configs must declare their rates or report $0.
- **Latency** — wall time per case; p50/p95 by nearest rank.

Scores always describe the **whole pipeline** (deterministic scan
+ panel), because that is the product being benchmarked.

## Scripted seats are not models

`bench/configs/oracle|blind|noisy.json` use replay seats
(`bench/scripts/*.json`): canned responses keyed by case id. The
oracle replays the ground truth, the blind seat reports nothing,
the noisy seat complains generically about everything. Their
scores validate the harness and the scoring math — nothing else.
For orientation, on corpus v0: oracle recall 1.000 with escaped
rate 0.129 (the four ground-truth minor/nit defects are matched
but would not block the gate — the escaped definition working as
specified); blind recall 0.452, which is exactly the deterministic
layer's share; oracle precision 0.775, because deterministic
findings that duplicate a panel finding under a dissimilar title
count as false positives — a real observation about cross-layer
dedup, kept visible rather than tuned away.

## Real baselines

First real-provider attempt (2026-11-04, via the internal swarm
runner; config `panel-gemini-nvidia`, 8-case public subset spanning
secrets, injection, auth, payments, concurrency, the real case, and
2 clean controls): **degraded — not quotable as the panel
baseline.** Gemini hit its free-tier daily quota (HTTP 429, plus
503 overloads) on all 8 cases, so the correctness lens never ran;
NVIDIA served the operations lens on 6 of 8. Even so, the subset
scored recall 0.875 and escaped-defect rate 0.125 (the one escape
was the concurrency case, where both seats errored), p50 latency
2.7s. A clean two-family baseline awaits a quota reset and the
OpenAI seat; it will be run over the full public split and recorded
here with its date and panel health.

**First full-public-split baseline (2026-11-04, config
`panel-baseline-2026-11-04`): quotable, with caveats.** Gemini was
still quota-dead at preflight (HTTP 429) and was excluded before
the run; the panel that served was OpenAI (gpt-5.4, correctness) +
NVIDIA (nemotron-3.5-lightning, operations) + DeepSeek
(deepseek-flash, correctness), seats injected from the swarm's
llm_chain via `bench/scripts/run_panel_baseline.py`. All 27 public
cases ran, **zero degraded, 81/81 seat jobs ok**: **recall 24/24
on the public split, escaped-defect rate 0.000** — against the
since-superseded naive precision 0.209, a
clean-case BLOCKED rate of 0.40 (2 of 5 clean
controls gate-blocked on false positives) and a clean-case
any-finding rate of 0.60 (3 of 5). Full numbers, per-family
and per-lens breakdowns, and the caveats that must travel with the
headline are in `bench/BASELINE-2026-11-04.md`, with the official
report and raw records beside it; corrected figures and intervals
are in that file's measurement-repair addendum (§6). A
Gemini-inclusive baseline still awaits a quota reset.

## Holdout discipline

Holdout cases score in the full (internal) report only.
`bench report --public` drops every holdout record **before**
scoring: no holdout id, title, row, or per-case number can appear
in public output. Public claims quote public-split numbers.
(Which split a run executes is a separate knob: `bench run
--split public|holdout|all` — see the usage examples at the top
of this file.)
