# Step 1 offline analyses A1–A6 — SUMMARY (2026-11-05)

Working file for the B2 follow-up to the registered confirmation
failure (`issue-reports/2026-11-05-codereview-confirmation-clean-blocked.md`;
expert solution `codereview-confirmation-clean-blocked-solution-2026-11-05.md` §3/§5).
Sets used are DEV data for policy design (declared): A5 holdout +
expanded-clean (consumed once by attempt 1) and the v1 public split
scored on its ORIGINAL 24 labels (the 10 `adjudication_added`
corpus entries excluded). No registered record or result was
altered; no `src/` changes; no registered runs.

Definitions: live grouping = the merged findings as stored in the
records (`core.merge_findings` output); live matching =
`bench._finding_matches`/`score_case`; merged precision =
`score_confirmation_v2.merged_blocking_precision` semantics; base
severity = `profile_demotion.from` restored; evidence class from
sources × family map (E0 deterministic, E1 ≥2 distinct families,
E3 single source; E2 never occurs offline).

## A1 — Blind adjudication of the 33 ( ⚠ interpretation changes)

Final verdicts (n=33): **REAL_DEFECT 18 (54.5%)**, HARDENING_ONLY 6,
FALSE_POSITIVE 7, NO_MAJORITY 2. `material_real_share_flag = TRUE`.

- 5 qualifying probes executed the diffs' own code; all 5 claims
  CONFIRMED (non-UTF-8 crash `97d5edda477f`; rounding order
  `4825814c1e37` — with the caveat that the case's `parse_money`
  quantizes inputs by design, so the defect rests on `line_total`'s
  implied contract; None-sentinel double charge `12bef37f9dfb`;
  both DST findings `d2826f58c92e`, `498b7807446e`). Probes decided
  5 finals, changing 3 vs the panel alone.
- Panel-only REALs include the MySQL placeholder mismatch, both
  circuit-breaker races, the Go 1 MiB silent truncation, the DLQ
  retry loop, the AbortSignal overwrite (E1 dual-raised, reduced-
  independence panel — flagged), the migration lock, the /100
  currency divisor, `Optional.of` NPE (unanimous; Java probe
  not_run — no JDK in the sandbox), both PDO findings (unanimous),
  the SSRF TOCTOU (one twin REAL, the other HARDENING), and the
  413 `req.destroy()` RST.
- Consequence per the solution (§3 A1 / §6.7): **a majority of the
  "false positives" on the expanded-clean stratum are real defects
  in code labelled clean.** The registered result stands untouched
  (22/34 BLOCKED under the frozen scoring), but the labels need
  dated amendments, and the issue report's root cause 3 (seat
  severity calibration) is substantially weakened for this stratum:
  blind adjudication backs the panel 18/33, plainly refutes only
  7/33. Caveats: Gemini was quota-down (429, hard stop) and
  substituted with second models from non-raiser families; NVIDIA
  lightning returned 14/33 invalid votes; two twin-pairs split
  (adjudication noise is real); NO_MAJORITY findings keep their
  votes unforced.

## A2 — Corroboration cost on recall (31 labelled defects)

- Greedy TP construction (score_case's one-finding-per-defect
  pick): TP findings E0/E1 = **16.1% (5/31)**; A5 42.9% (3/7),
  public 8.3% (2/24). Case-level ALL_BLOCKING_TP_E01: 13.8% (4/29).
- Any-match semantics (the precision scorer's D semantics — a
  defect survives if ANY blocking finding matching it is E0/E1):
  **15/31 (48.4%)** survive a block-only-E0/E1/E2 rule; A5 4/7,
  public 11/24.
- Either way the expert's "≥85% E0/E1 ⇒ corroboration is cheap"
  test FAILS: true defects are predominantly single-source at
  blocking tier. Corroboration alone is not cheap; verification
  (R3 confirmation, probes) has to carry the recovery.

## A3 — Rule sweep (live grouping; sanity checks all PASS)

Sanity: R1 reproduces expanded-clean 22/34 and A5 precision 0.875
(the registered figures); R0 reproduces strict 32/34; R0/R1 recall
1.000 on A5 and public (original labels).

| Rule | Comb. recall (any-sev) | Comb. precision | Comb. clean-BLOCKED | J | Shortlist |
|---|---|---|---|---|---|
| R0 strict | 1.000 | 0.756 (D31/U10) | 0.872 (34/39) | 0.128 | FAIL |
| R1 B1 | 1.000 | 0.939 (D31/U2) | 0.590 (23/39) | 0.410 | FAIL |
| R2 block-only-E0/E1/E2 | 1.000 | 1.000 (D15/U0) | **0.051 (2/39)** | **0.949** | **PASS** |
| R3 (= R2 offline) | 1.000 | 1.000 | 0.051 | 0.949 | PASS |

Per-bundle: R2/R3 also pass the A5 bundle (clean 2/34, J 0.941)
and the public bundle (clean 0/5, J 1.000).

Two readings that must travel with the table:
1. Recall is the registered any-severity definition. At BLOCKING
   tier, R2/R3 recall is **0.484 combined (15/31)** — the gate
   stops blocking 16 of 31 labelled defects, which remain visible
   as non-blocking majors. That gap is exactly what R3's
   cross-family confirmation and B3's probes exist to close; it
   cannot be measured offline (confirmation needs regeneration).
2. With A1 in hand, part of R2's clean-rate gain on expanded-clean
   is demoting findings blind adjudication calls real defects in
   mislabelled cases — another reason R3's confirmation step is
   load-bearing rather than decorative.

R3 confirmation load (E3 blocking findings at base severity that
would go to cross-family confirmation): expanded-clean 75,
public 77, holdout 25 — 177 across all records.
R4: **not evaluable offline — pilot item.** 0 of 387 findings
carry a `trigger` field or any trigger-like key; findings carry
`evidence_quote` only, so no deterministic trigger check exists.

## A4 — Seat emission + agreement (base severity, combined)

Majors per case, any-source — clean (39): **nvidia 1.154**,
deepseek 0.538, openai 0.333, deterministic 0.026. Defect (29):
nvidia 0.828, openai 0.690, deepseek 0.621, deterministic 0.207.
Per-set split matters: attempt-1's clean noise was correctness-led
(deepseek 21 + openai 12 of the 33 recorded), the public split's
was nvidia-led (45 of its 47 clean blocking findings sole-source).
Over-flagging is not one seat — the worst emitter changes with the
set, which argues against seat-specific caps as the main lever.
Agreement is near-zero almost everywhere (clean: every
off-diagonal 0.0 except deepseek↔openai 0.048/0.077; defect: all
≤ 0.156) — the expert's uncorrelated-errors premise holds.

## A5 — Probe feasibility (heuristic audit classifier)

**76.1% of blocking findings are executable claims (105/138)** —
expanded-clean 45.5% (15/33), defect-case findings 85.7% (90/105).
Well above the solution's ≥40% bar for prioritising B3 (E2
reproducer-backed blocking).

## A6 — Pipeline audit

Bottom line: **attempt 1 measured neither the raw panel + B1 nor
the full product gate.** It measured the full in-core adjudication
pipeline that needs no external inputs — deterministic pre-scan,
seat calls + repair, grounding validation + re-ground pass (§2b,
fired: 9 reground_confirmed), coverage, merge, line basis, Policy
B1 (54 demotions), platform-scope labelling (classified none),
cross-family confirmation (§2c, fired: 62 labelled), dispute
adequacy grading (25 disputes) and binding Tech Lead adjudication
(25, all sustain_finding, 12 with rubric downgrade). Absent were
every caller-supplied-input stage: project policy (Epic B) and
with it risk/tiering/diversity, the Epic C evidence rule,
precedents, fixture scope, a designated tech_lead, probe_fn
(probe rounds never ran — a `needs_probe` would have escalated),
tech-lead shadow, file_context, agents_context, test_results,
waivers, notifications. On the expert's three named stages:
re-ground RAN, cross-family confirmation RAN, and "grounding
demotion" does not exist — grounding failure never demotes; only
a seat's own withdrawal in re-ground removes a finding, and an
unresolved re-ground leaves the finding blocking (sole effect: a
would-be PASS flips to INCONCLUSIVE; never fired here).
Persistence caveat: `generation.to_attempt_record` drops the
report's side lists (withdrawn/disputed/refuted/escalated/…), so
findings moved out of `report["findings"]` are uncountable from
attempt-1.jsonl alone. Seat prompts in the bench path are the
product's own core prompts.

## Decision (solution §5 procedure)

1. R2/R3 meet the dev targets (clean-BLOCKED 0.051 ≤ 0.15,
   recall 1.000 ≥ 0.95) → **Option A proceeds: B2 becomes the
   registered-policy candidate.**
2. Blocking-tier recall suffers under R2 (0.484) and A2's ≥85%
   cheapness test fails → B2 ships in its **R3 form** (E3 majors go
   to cross-family confirmation; R4's trigger rule joins at the
   pilot, where it becomes evaluable) and **B3 is prioritised**
   (A5: 76.1% executable), not staged as an afterthought.
3. Option B remains a component (prompt/rubric calibration
   measured on dev), not the lead lever (A4).
4. **Option C is NOT triggered** — a rule met the dev targets.
5. A1 rider: before the fresh-set build (Step 4), the
   expanded-clean labels need dated amendments (18 real defects
   found); the registered attempt-1 result is not altered. The
   fresh registration should also state explicitly whether its
   recall threshold is any-severity or blocking-tier — the sweep
   shows the two diverge sharply under B2 (1.000 vs 0.484 on dev).

## Artifacts

`a1-packets.json`, `a1-verdicts.json`, `a1-summary.json`,
`analysis_sweep.py`, `a2-corroboration.json`, `a3-rule-sweep.json`,
`a4-seat-emission.json`, `a5-probe-feasibility.json`,
`a2345-summary.json`, `a6-pipeline-audit.json`, `a6-summary.md`,
this SUMMARY. Left UNCOMMITTED: repo HEAD moved c9568eb → c4d34d1
during the A1 run (another actor's owner-disposition commit);
committing the analysis is the parent's call. Pre-existing
untracked `bench/generation-cache/` is not part of this work.
