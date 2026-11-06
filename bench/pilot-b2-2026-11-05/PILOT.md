# Policy B2 dev pilot — results (2026-11-05)

Live product pipeline, gate profile `corroborated`, v1 panel [openai, nvidia, deepseek], dev data only (public split + expanded stratum, labels as amended 2026-11-05). Paired rows are the SAME responses re-evaluated offline through core.evaluate_gate_policy (§6.1); the live row is the full pipeline outcome.

Provenance: 62 cases, one live run each. The main run's final record (xc-tz-aware-scheduling) flushed late and one case (xc-token-bucket-limiter) was completed by a same-day top-up run under the identical configuration; the duplicate tz-aware record was deduplicated keeping the main run's. The paired `strict`/`balanced` rows evaluate the B2-prompt responses under those policies — they are paired policy comparisons, not the v1 baseline numbers. 14 of 62 runs are marked degraded, every one with 'reviewer failure' among its causes (a seat failed and a fallback or partial panel served); gates were still decided on all 62. Under a registered run those degraded cases would matter — seat reliability is the pilot's main operational warning for Step 6.

| profile | clean-BLOCKED (combined) | recall any-sev | recall blocking-tier | merged precision | J |
|---|---|---|---|---|---|
| live | 0.125 (5/40) | 1.000 | 0.706 | 1.000 | 0.875 |
| strict | 0.925 (37/40) | 1.000 | 0.971 | 1.000 | 0.075 |
| balanced | 0.625 (25/40) | 1.000 | 0.941 | 1.000 | 0.375 |
| corroborated | 0.125 (5/40) | 1.000 | 0.706 | 1.000 | 0.875 |

Trivial baselines (combined): always-pass clean-BLOCKED 0.000 / recall 0.000 / J 0.000; always-block 1.000 / 1.000 / J 0.000; deterministic-only clean-BLOCKED 0.025, recall 0.265, J 0.240.

Live extras: degraded cases 14 (causes: {'reviewer failure': 14, 'coverage incomplete': 1, "corroboration unavailable for 1 unverified major(s) under gate profile 'corroborated' (policy B2 degraded mode)": 1}); unverified majors 70; blocking findings by evidence class {'E1': 21, 'E0': 10}; corroboration outcomes {'unresolved': 69, 'refuted': 55, 'confirmed': 14, 'unavailable': 1}; paired-replay agreement 62/62.

Label-adjusted clean (live): 0.080 (2/25), Wilson 95% [0.022, 0.25] — the as-labelled rate is 0.125 (5/40); the gap is cases whose only blockers are findings A1 adjudicated REAL defects in mislabelled 'clean' code.

## Prediction for the registered confirmation (§6.3)

- clean-BLOCKED: point 0.080, 95% interval [0.022, 0.25]
- recall (any severity): point 1.000, 95% interval [0.898, 1.0]
- recall (blocking tier): point 0.706, 95% interval [0.538, 0.832]
- merged blocking precision: point 1.000

Pilot bar (solution §6.2): clean-BLOCKED ≤ 0.20 on dev clean — see the live row (as-labelled and adjusted) above.
