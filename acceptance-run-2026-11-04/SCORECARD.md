# Tech Lead acceptance run — measured scorecard

**Run:** 2026-11-05 01:14–02:58 ET (single complete run; an
earlier launch died in a sandbox /tmp wipe after 16 baselines
and was discarded — this scorecard is measured only from the
run recorded here).
**Seat:** DeepSeek (connector surrogate via the swarm
`llm_chain.call_deepseek`), family `deepseek` — independent
of every raiser/refuter family in the corpus.
**Protocol:** shadow Tech Lead, adjudication protocol v1,
rubric v1; full protocol per corpus (48 baselines + 192
mutation adjudications). Precedent store never consulted;
probes presented as shipped context, never executed
(scorecard's scored-decision definition).
**Full record:** `acceptance-run.json` (per-case entries,
scores, paraphrases, flips). Driver: `run_acceptance.py`.
Progress log: `progress.log`.

## Measured gates (thresholds from the corpus scorecard.json)

| Gate | Measured | Threshold | Verdict |
|---|---|---|---|
| M1 false dismissals on real findings | **2** (L06, P06) | == 0 | FAIL |
| M2 probe-settled accuracy | **0.25** (3/12) | ≥ 1.0 | FAIL |
| M3 overall accuracy | **0.333** (16/48) | ≥ 0.90 | FAIL |
| M4 mutation flip rate | **0.255** (49/192) | ≤ 0.05 | FAIL |
| M5 protected + insufficient escalated | **1.0** (5/5) | ≥ 1.0 | PASS |
| M6 double-draw agreement on majors | **0.706** (12/17 measured) | ≥ 0.90 | FAIL |

**Unlock: NO.** Binding Tech Lead authority is not earned;
the Tech Lead stays in shadow mode. All six gates must pass
on a single run; five failed.

## Failure modes (from the recorded entries)

- **Over-escalation dominates:** 36/48 baselines scored
  escalate. Escalation is the cheap error — it is why M1 is
  only 2 — but it fails M2/M3 outright: the seat would not
  commit on probe-settled cases (3/12) or on the positive
  controls (2/15 sustained).
- **The 2 false dismissals** are sustain_refutation on real
  findings L06 and P06. Under the adopted asymmetry these
  are the expensive errors and alone keep M1 closed.
- **Instability is broad, not mutation-specific:** flips by
  mutation — position_swap 15, family_swap 11, vendor_strip
  13, reason_paraphrase 10. (Family labels and vendor names
  are scrubbed from the presentation by construction, yet
  decisions still moved — the variance is in the seat's
  reasoning, not in label leakage.)
- **M6 coverage caveat:** only 17 of 47 majors reached a
  merits decision on draw 1 and so took a second draw;
  agreement is measured over those 17 (12 agreed). The other
  30 escalated on the first draw — consistent with the
  over-escalation mode above.
- **What worked:** the protected/insufficient set (X01–X03,
  I01, I02) escalated 5/5, and the dismissal-evidence rule
  cases (W01, W02, W05, W06) all scored correct via
  escalation.
