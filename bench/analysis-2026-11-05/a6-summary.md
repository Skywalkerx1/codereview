# A6 — Pipeline audit: what Baseline v2 confirmation attempt 1 actually measured

Repo master `c9568eb`. Read-only audit; machine-readable version: `a6-pipeline-audit.json`.

## Bottom line

**Not raw panel + B1 alone, and not the full product gate either:** attempt 1 measured
the full in-core adjudication pipeline that needs no external inputs —
deterministic scan, product seat calls/repair, grounding validation + re-ground (§2b),
coverage, merge, line basis, Policy B1, platform-scope labelling, cross-family
confirmation (§2c), dispute adequacy grading and binding Tech Lead adjudication —
all demonstrably exercised in the records (54 B1 demotions, 9 re-ground confirmations,
62 `cross_family` labels, 25 disputes all Tech-Lead-sustained) — while every stage
that needs a caller-supplied input was absent because the confirmation chain passes
none of them: project policy (Epic B) and with it risk/tiering/diversity, the Epic C
evidence rule, precedents, fixture scope, a designated Tech Lead, `probe_fn`,
tech-lead shadow, `file_context`, `agents_context`, test results, waivers, notifications.

## Call chain

`run_registered_confirmation.py:162` → `generation.run_generation`
(panel openai/nvidia/deepseek; explicit binding openai→correctness,
nvidia→operations, deepseek→correctness; fallbacks `{correctness: openai}`;
`gate_profile="balanced"`; `allow_major=False`, `strict=False` — config defaults,
the bench config file sets neither; `seat_meta` from the config)
→ `bench/generation.py:728` → `core.run_review(diff, dict(seats), context=…, …)`
with **no** `policy`, `precedents`, `evidence`, `probe_fn`, `tech_lead`,
`file_context`, `agents_context`, `fixture_scope`, `test_results`, `lens_seats`,
`waivers` or `notify`.

Seat prompts are the **product's own**: core's `_REVIEW_PROMPT`, `_REGROUND_PROMPT`,
`_XCONFIRM_PROMPT` and the Tech Lead prompt in `_tech_lead_call`. Bench-specific
parts are only the `GenerationSeat` cache/retry wrapper, the bench transports/params,
and the `[bench-case: …]` context string. No file-context or AGENTS.md prompt
suffix was attached.

## Stage table (execution order)

| # | Stage (core.py) | Status | Record evidence |
|---|---|---|---|
| 1 | Gate-profile resolution (:3766) | RAN | All 43 records: `gate_profile={balanced, source: argument}` |
| 2 | Deterministic pre-scan `deterministic_scan` (:517, call :3782) | RAN | 4 merged findings with `deterministic` source. Test-failure rule inert — `test_results=[]` |
| 3 | Archived-section exclusion pre-batching (:3799) | CONDITIONAL, no-op here | No `review-*/` / `gate-attempts.*` paths in bench diffs |
| 4 | Seat calls + repair `_run_jobs` (:4014); fallback serving (:4053) | RAN; fallback wired, **not served** | 129 reviewer_reports in attempt file (43×3, all ok). 132 seat jobs = full 44-case generation universe (manifest); 1 case (`xc-redacted-logging`) unscored, not in attempt file. No `fallback_for` on any report |
| 5 | Grounding validation (§2b, :4121) | RAN | 272 findings: grounded 263, reground_confirmed 9, unresolved 0 |
| 6 | Re-ground pass (§2b, :4260; `_reground_call` :1075) | RAN conditionally — **fired** | 9 findings `grounding=reground_confirmed` + `reground_seat` (openai 5, nvidia 2, deepseek 2). Withdrawals uncountable from attempt records (see persistence gap) |
| 7 | Coverage accounting (§2a, :4307) | RAN | Indirect only: `degraded=false`, `degraded_causes=[]` on all 43 (coverage section dropped by the adapter) |
| 8 | `merge_findings` (:2662, call :4348) | RAN | Multi-source merges present; scorer removed 12 duplicates (holdout) |
| 9 | Line basis `_apply_line_basis` (:607, call :4351) | RAN | 157/272 findings labelled (blob 154, diff 3); rest unlabelled by design |
| 10 | **Policy B1** `_apply_gate_profile` (:2587, call :4359) | RAN | **54 demotions** (51 major→minor, 3 blocker→minor); demoted findings carry no `cross_family` — B1 runs before confirmation |
| 11 | Archived-text classification (:4366) | DID NOT RUN | Gated on non-empty `archived_sections`; none existed |
| 12 | Fixture classification (:4374) | DID NOT RUN | `fixture_scope=None` — never passed |
| 13 | Precedent classification (:4454) | DID NOT RUN | `precedents=None` — never passed. (12 findings carry an inert `precedent_eligible` mark from the Tech Lead branch) |
| 14 | Platform-scope labelling `_platform_scope` (:2017, loop :4467) | RAN, classified none | 0/272 findings carry `platform_scope` |
| 15 | Cross-family confirmation (§2c, :4486; `_xconfirm_call` :1098) | RAN conditionally — **fired** | 62 findings carry `cross_family`: confirmed 29, tech_lead_sustained 25, unresolved 5, multi_family 3. 50/53 post-B1 blocking findings labelled; the 3 unlabelled are deterministic-only |
| 16 | Dispute adequacy grading + shadow reason-check/trace-gate (:4583) | RAN conditionally — **fired** | 25 `dispute` blocks: adequacy weak 23 / strong 2; every one carries `reason_check` + `trace_gate_shadow` |
| 17 | Tech Lead **shadow** adjudication (:4615) | DID NOT RUN | `tech_lead_shadow=False` default, never passed |
| 18 | Tech Lead adjudication, binding (:4680/:4731) | RAN conditionally — **fired** | 25 `adjudication` blocks, all seat deepseek (auto-selected independent seat — no designated `tech_lead` was passed), all `sustain_finding`; 12 with `severity_before_adjudication` (rubric downgrade) |
| 19 | Probe rounds (:4736) | DID NOT RUN | `probe_fn=None` — never passed; all 25 adjudications `probe_rounds=0`. A `needs_probe` decision would have escalated instead |
| 20 | Gate computation `_gate` (:3434, call :4866) + PASS→INCONCLUSIVE adjustments (:4971/:4998) | RAN; adjustments did not fire | Gates: blocked 30, pass 13, inconclusive 0 |
| 21 | Project policy evaluation, Epic B (:5028) | DID NOT RUN | `policy=None` — never passed; profile source `argument` confirms no policy file was involved |
| 22 | Risk (E1) / tiering+escalation (E2/E4) / diversity (E3) | DID NOT RUN | All policy-gated; single-stage full panel ran instead |
| 23 | Evidence rule, Epic C (:5103) | DID NOT RUN | `evidence=None` — never passed |
| 24 | Notifications (L4) / progress | DID NOT RUN | `notify=None`, `progress=None` — never passed |

## The expert's three stages, precisely

- **Re-ground pass — ran.** Conditionally on ungrounded findings, and the records
  prove it fired (9 `reground_confirmed`).
- **Cross-family confirmation — ran.** Conditionally on single-family blocking
  findings after B1, and the records prove it fired (62 labels; 25 refutations
  went on to dispute + Tech Lead).
- **"Grounding demotion" — no such stage exists.** Grounding failure never demotes
  a severity and never, by itself, removes a finding:
  1. First-pass failure only marks `grounding="ungrounded"` and queues re-ground.
  2. A finding leaves the gate list in re-ground **only if a seat itself withdraws
     it** (`_reground_call` → `withdrawn`, preserved in the full report's
     `withdrawn_findings`); a confirmed re-ground restores it as
     `reground_confirmed` with the validated quote.
  3. If re-ground is **unresolved**, the finding **stays at its original severity
     and still blocks**; the only consequence is at gate level — a would-be PASS
     flips to INCONCLUSIVE ("a human must decide"). That flip never fired in
     attempt 1 (0 unresolved, 0 inconclusive).
  The only demotion in the path is B1, which is lens-based (solely-operations,
  uncorroborated), not grounding-based.

## Persistence gap (why some stages can only be bounded, not counted)

`bench/generation.py:569` `to_attempt_record` persists only `findings`,
`reviewer_reports`, `gate`, `gate_profile`, `degraded(_causes)`, `seat_lenses` and
identity/cost fields from the full report. It drops `withdrawn_findings`,
`disputed_findings`, `refutation_weak_findings`, `adjudicated_refuted_findings`,
`escalated_findings`, `standing_findings`, `out_of_scope_findings`,
`archived_text_findings`, `fixture_*`, `policy`, `risk`, `tiering`, `evidence`,
`coverage`, `gate_reasons` and the shadow top-level lists. So any finding a stage
moved *out of* `report["findings"]` is invisible in `attempt-1.jsonl` — e.g. a
re-ground withdrawal count cannot be recovered from the attempt records alone.
What *is* recoverable is what surviving findings carry: `dispute` + `adjudication`
on all 25 Tech-Lead-sustained findings, `profile_demotion` on all 54 B1 demotions,
`reground_seat` on all 9 re-ground confirmations, `cross_family` on 62 findings.

Also note the count reconciliation: **129 reviewer_reports in `attempt-1.jsonl`
(43 complete cases × 3) vs the 132 seat-job figure**, which is the generation
universe over all 44 registered cases (131 valid + 1 unscored-infra) in the
manifest / RESULTS document.
