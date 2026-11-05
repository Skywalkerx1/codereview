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

Suite-pinned versions of the guard properties live in
`tests/test_v111_dispute_probes.py`; the hardening changes
(marker, callee key, config validation, non-dict walk) are
pinned in `tests/test_v111_hardening.py`.
