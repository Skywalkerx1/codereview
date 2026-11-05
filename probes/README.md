# Dispute probes — PT-1 open-refutations track (2026-11-04)

Rerunnable probes for the 17 open CodeReview disputes
(open-refutations solution §§2–3). Each script writes its
full-text result to `results/` and reports facts; probes can
only rebut a claim, never sustain one, and nothing here
adjudicates — the ruling packets carry the recommendations
to the owner's session.

| Script | Finding(s) | What it settles |
|---|---|---|
| `regeneration_probe.py` | 7baa0147d8d4, 7ea4e96603e9, 212878ab6bba | Re-renders the cited records at HEAD + a synthetic both-ok/degraded-by-coverage fixture. First claim retires (renderer agrees with JSON); the pair converts to a new renderer finding (the misleading boilerplate persists at HEAD). |
| `oversize_probe.py` | 6219e04d4c00 | Unplaceable section is flagged incomplete and degrades the run with the reason stated; placeable sections never exceed budget. |
| `lens_mapping_probe.py` | 35dbb7d20941 | Over all orderings/failing seats, the serving verification fallback is the one configured for the seat's assigned lens per `_reviewer_tasks`. |
| `fix_verification.py` | 19a537eb386b, 931ea3882b76 | Parent-fail: each fix's test passes at the fix commit and fails at its parent, in the shape the claim described. |
| `stub_payload_rerun.py` | e1e22d48db4d | Payload `model` present at HEAD for presets, overrides, and the custom escape-hatch spec (suite tests + direct capture). |
| `unknown_family_probe.py` | 3d9645200bc5 | Unknown family fails closed: construction, Tech Lead selection, cross-family marking, record-verify two_families. |
| `duplicate_seat_probe.py` | 78ddf4d5ea27 (+ 19a537eb386b's seam) | Demonstration: a pooled seat + role override records a model that never serves. Name-level permutation determinism asserted. |
| `reachability_probe.py` | f56cd4a0b6c9 | No concrete harm sequence from repeated role assignment: merges name-guarded, builds side-effect-free. |
| `finding_public_probe.py` | 4ce0212286e0 | Captures the actual adjudication prompts (re-ground, x-confirm, Tech Lead) and measures the evidence slice; post-hardening runs show the explicit truncation marker. |
| `records_scan.py` | a3a2d492b51a | Scans gate-attempts.* + all committed records for paths/hostnames/connectors/accounts/key-shaped strings, plus the attempts-log telemetry inventory. Evidence for the owner's public-profile decision. |

## Gap pass — the 19 computed-open disputes with no PT-1 packet (2026-11-04, branch gap-pass)

Worksheet: `~/workspace/goals/reviewloop-multi-model-code-review-product/files/disputes-gap-worksheet-2026-11-04.md`; packets: `../goals files/ruling-packets-gap-2026-11-04/`. Group 1 (record-only backfill) was recorded by the owner directly into `dispositions.jsonl` (commit 0cb893e) and is not probed here. Group 3's two re-raise IDs (290d549f2809, ae9e58378eee) share the Group-2 originals' probes.

| Script | Finding(s) | What it settles |
|---|---|---|
| `gap_bench_force_probe.py` | 474297e6ffdc | Ruling-pack P3 executed: a forced rerun with healthy seats is accepted despite a stored degraded record; a forced rerun whose NEW records degrade is refused and the previous file survives. |
| `gap_percentile_probe.py` | 09c536d15270 | P4 property test: 20,000 (n, pct) pairs, zero disagreements with textbook nearest-rank, zero out-of-range indexes; the disputed N=2/p50 case executes to rank 1 (both sides' worked examples said 2). |
| `gap_attempts_log_probe.py` | bca4074a632c | P5 provenance: --attempts-log is settable only via argv (one argparse definition; no env/config/policy source); functional CLI run writes the entry to an operator-supplied outside path. |
| `gap_commonpath_probe.py` | eae8137a6db3, 3cecf66f6ce5 (+ re-raises 290d549f2809, ae9e58378eee) | Both loaders route through the shared `_is_within` helper (fail-closed under a simulated cross-drive ValueError); git shows the unguarded pattern at 4e5cbd8^ and its replacement by 4e5cbd8. |
| `gap_doctor_timeout_probe.py` | 3fc4862824c9 | All three construction sites receive agent_timeout (instrumented); hanging seat bounded at ~1s under --timeout 1 at HEAD; parent-fail at 2dd114e^ — the same call waits the seat's full 12s (fix 2dd114e, v0.11.1). |
| `gap_matcher_probe.py` | d93089253022 | P9 matrix: sibling prefixes never match ('foobar/x.py' vs 'foo' = False); true children, exact, glob, and dir/** forms behave. |
| `gap_quorum_probe.py` | c5f02551d077 | The claim's scenario (2 configured, 1 succeeds, finder clears) is INCONCLUSIVE with the quorum reason in both relaxed and strict modes; solo panel passes with the v0.9.6 solo labels. |
| `gap_providers_probe.py` | 0e57186e8be8, 1aec997aaec4, 0ad4ed7db98e, 2242edbba9c9 | P11 colon-command cases (command remainder preserved verbatim); P12 permutation + case-folding matrix (cross-kind collision raises in every order; control builds); P14 import guard (os/signal at module scope + functional process-group kill). |
| `gap_prompt_slice_probe.py` | 3f50bf6b3349 | `_prompt_slice` output measured against cap: every over-cap input returns cap + up to ~98 chars (the appended truncation marker); the docstring promises at most cap. |
| `gap_scan_exposure_probe.py` | 20e4194e5ed9, ec925437d0e3 | The scan result file at HEAD republishes real local paths (the refutation's 'placeholder' premise fails: /home/hatch is this host's real home and the cited files exist); 'admin@example.com' traces to example code inside reviewed diffs, and all 9 account_id samples are that one string. |

Suite-pinned versions of the guard properties live in
`tests/test_v111_dispute_probes.py`; the hardening changes
(marker, callee key, config validation, non-dict walk) are
pinned in `tests/test_v111_hardening.py`.

## Shadow-branch review — the 5 disputes from the shadow-tech-lead branch review (2026-11-04)

Packets: `~/workspace/goals/reviewloop-multi-model-code-review-product/files/ruling-packets-shadow-2026-11-04/`; source record: `review-branch-out/codereview-20261105-011527.json`. All probes ran against the MERGED tree (main HEAD 2fbf94f), not the branch the review saw.

| Script | Finding(s) | What it settles |
|---|---|---|
| `shadow_probe_signature_probe.py` | 833912a09fa3 | Shadow needs_probe with the real make_probe_fn records a swallowed TypeError and the spec never executes; the same fn works with the documented two-arg call; the suite's one-arg stub is why the mismatch stayed green. |
| `shadow_test_runner_probe.py` | 4cf81c69d7cf | Same failing test with/without the `__main__` guard: probe agrees with the runner with the guard, reports pass with zero tests executed without it. |
| `shadow_acceptance_empty_probe.py` | 633acb885291 | Empty corpus crashes run_acceptance under both scorecard shapes: ZeroDivisionError at M3 (set-less) / KeyError at M1 (shipped scorecard). |
| `shadow_trace_gate_probe.py` | 4cba208656d3 | The forward reference resolves at call time: _trace_gate_shadow executes through _scan_functions and returns verdicts in both directions. |
| `shadow_attach_keys_probe.py` | 97feb799979e | None/raising/absent-path source lookups never crash attach_function_keys and never key a finding; the guard lives in function_key. |

## Closing round 1 workup — the closing-chain round-1 disputes + findings (2026-11-04)

Packets: `~/workspace/goals/reviewloop-multi-model-code-review-product/files/ruling-packets-closing-r1-2026-11-04/`; source records: `review-closing-r1/codereview-20261105-031927.json` (counting), `review-closing-r1-attempt1/codereview-20261105-031306.json` (preserved), `review-shadowfixes-out/codereview-20261105-032130.json`. All probes ran at span head 0a2c9f2 (fixes verified again post-fix on branch closing-fixes). Result files: `results/closing*.txt`.

| Script | Finding(s) | What it settles |
|---|---|---|
| `closingA_archived_rule.py` | b2b1f776d566, 0011f9970c38 | _archived_rule is first-component-only: top-level review-* classifies, nested review dirs do not. |
| `closingA_archived_text_dep.py` | (archived-text class) | Archived diff sections are excluded by quote-basis; raw text and headerless sections are not. |
| `closingA_batch_budget.py` | 07a9a2646925, 023d2c9b1b20 | Budgets 0/-3 return bounded incomplete=True; no loop, no range() ValueError. |
| `closingA_function_key.py` | cc0e75a507fd | Flat 5000-term chains raise RecursionError in the keying path (fixed ee8b028). |
| `closingA_probe_typeerror.py` | 21bb4af17e22 | Internal TypeError from a correctly-wired probe is misclassified wiring_error; RuntimeError classifies correctly; make_probe_fn path is honest. |
| `closingA_render_fields.py` | 7514429a36b2, 7c8ec49fb549 | render_markdown tolerates every grounding/family/tier absence combination. |
| `closingA_serving_name.py` | dd391599588d | Serving-name attribution names the provider actually called (fidelity-correct). |
| `closingA_shadow_cache.py` | 62576759aaad, 03eb527e1e44 | Cache hit lent the drawing seat's independence to a reduced seat (fixed fab60f5). |
| `closingA_shadow_tuple.py` | ba2479886886, 5683aa292958 | All shadow evidence targets are arity 3; write_report succeeds; sidecars attach + validate. |
| `closingA_sidecar_sha.py` | 531bd4e5a458 | Sidecar validation fails closed on empty/malformed/traversal sha refs. |
| `closingA_test_coverage.py` | 887c490bd9eb | CLI main-level coverage map by subcommand (feeds the worksheet). |
| `closingA_verification_error_evidence.py` | 30b316c77b43, 328a5ff6fa51, 2eb60efeeace, f9ca50d61cad | Str error payloads are contained (inconclusive/degraded, no crash); resolution evidence is stored full, displayed capped at 300, sidecarred (Q7). |
| `closingA_verify_chain.py` | f43f2968433d, afe66da23121 | verify_chain returns normally with dispositions=None/[]; consumption is reported when supplied. |
| `closingB_acceptance_m4m6.py` | 60eb09183ee5, 1f64a6be5c10, e1570280c036 | M4/M6 denominators guarded: None + pass=False at zero; normal shapes measured + compared. |
| `closingB_bench.py` | e8c5d3fd8a25, 5e89ea2d985b, 55752b0dc5b7 | score_case tolerates None/missing confidence, ValueErrors on a string; matching is worst-severity-first; healthy forced rerun accepted over a degraded record, degraded rerun refused. |
| `closingB_cli_core.py` | 127ddee9be1b, 179ece0e030e, 7b4c5c8155ae, fd1ff955358e, ca9fcd9ca7c2, 32587160c9fc, 764e1d15a218, 934fab88a12e | _is_within fail-closed; _load_record_arg picks newest mtime; fixture scope reads rb+utf-8; --probe-timeout wired; set-but-empty CODEREVIEW_PROVIDERS falls through to saved config; setup wizard reachable on tty, clean rc=2 off it; doctor lacked the fallback==primary guard (fixed dee84d0); _evidence_main raised on collect failure (fixed a166ea3). |
| `closingB_cli_coverage.py` | 887c490bd9eb | The coverage map's raw form. |
| `closingB_disputes_registry.py` | 69a23ebb9f27, 44ace5079160 | disputes --check without inventory returns verdicts; registry.py:44-45 is the ROLES tuple, the boundary assertion is core.py:3250 (fail-closed). |
| `closingB_evidence.py` | 8f77565b56a4, 9489ee49db6f | Per-item timeout enforced at 1.0s; explicit timeout 0 swallowed by `or` into the 600s default. |
| `closingB_probe_sandbox.py` | 8479293e76ed, 6d2d43b7bc3e, b9e2819976fe, f46397a84121 | Sandbox terms as documented (fs reach real, env/cwd/net/timeout hold); kind-'test' discovery is basename-scoped but recursive into subpackages; kind-'test' runs via the unittest runner at HEAD. |
| `closingB_providers.py` | 536112b7d4dd, 610a06422389, ad6e36800a86 | Agent env is the 10-key allowlist, secrets absent, opt-in per-variable; non-positive agent timeout refused at construction (v13); intake agent_timeout forwards to the command. |
| `closing_bench_probe.py` | 78d6c78b3865, bbad4502fc6a (context) | bench.py's aggregate paths guard every denominator; the unguarded M3 quote was acceptance.py's, fixed by 6fa83f6. |
| `closing_disputes_probe.py` | 0bb1b939ab67, e9ef62daa1a0, 55c815ff5fbe, f43f2968433d | Computed inventory double-counted a duplicated record (fixed 564e054); span scan re-resolved ranges per record and dropped degenerate-range records (fixed 99fe588); verify_chain handles dispositions=None. |
| `closing_probe_scripts_probe.py` | 42011b7abf72, b7d613672e71 | No 'got' variable exists; captured initialised pre-patch; the hardening probe's git failure exits as CalledProcessError, not NameError. |
| `closing_records_scan_probe.py` | 6508525840b4, 99fe18f50ec3, 6458b8824abc | IPv4 pattern matches impossible octets; a non-blank malformed gate-attempts row aborts the scan; the §5.3 contract carries no age filter by design. |
