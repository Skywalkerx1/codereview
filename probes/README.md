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
