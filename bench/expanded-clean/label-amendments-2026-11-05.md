# Expanded-clean label amendments — 2026-11-05

Dev data only. This document describes the label-amendment format
introduced on 2026-11-05; it is not a registered result, an attempt
record, or a RESULTS document, and it alters none of those.

## Why

The expanded-clean stratum was consumed once by registered
confirmation attempt 1 and is now dev data for policy design
(`bench/analysis-2026-11-05/SUMMARY.md`). Blind adjudication A1 in
that analysis finally adjudicated 18 of the 33 recorded blocking
findings on this stratum `REAL_DEFECT` — i.e. real defects in code
that had been labelled clean. The registered attempt-1 result
stands untouched (it was scored on the original labels); these
amendments record the adjudicated reading for future dev use.

## Format

`case.json` has no pre-existing notes mechanism, so the smallest
structured amendment representation consistent with the existing
JSON format was added: an optional top-level `label_amendments`
field in the affected case's own `case.json`
(`bench/expanded-clean/<case-id>/case.json`). Each entry is an
object with:

- `date` — `2026-11-05`;
- `kind` — `label_amendment`;
- `original_label` — the label as originally recorded
  (`{"category": "clean", "expected": []}`);
- `finding_id`, `finding_title`, `finding_category`,
  `finding_severity`, `finding_sources` — the adjudicated finding
  exactly as recorded in
  `bench/analysis-2026-11-05/a1-verdicts.json`;
- `adjudication` — analysis name (`A1 blind adjudication`), its
  source files, `final_verdict` (`REAL_DEFECT`), `final_basis`
  (`majority` or `probe`), and the probe status / claim result /
  detail where a probe was recorded;
- `note` — the dated amendment note in prose.

## Preservation rule

An amendment is not a rewrite. In every amended `case.json` the
original label is preserved visibly and unchanged: `category`
stays `"clean"` and `expected` stays `[]`. The generation-v2 /
confirmation loaders read only `expected` (and require it to be
empty for this stratum) and ignore unknown fields, so scoring
behaviour on the original labels is unchanged; the amendments
are annotations for dev / policy-design use only.

`bench/expanded-clean/manifest.json` was deliberately NOT
changed: its sha256 is the registered SLOT-CLEANHASH verified by
`bench/scripts/verify_registration.py`, and the manifest carries
no per-finding label detail to amend.

## Coverage

18 findings across 15 cases (finding ids per case are listed in
each case's `label_amendments`):

`xc-batch-delete-guarded`, `xc-bounded-response-read`,
`xc-circuit-breaker` (2 findings), `xc-context-http-timeout`,
`xc-deadletter-worker`, `xc-decimal-money`,
`xc-fetch-timeout-abort`, `xc-guarded-migration`,
`xc-idempotency-keys`, `xc-intl-currency-format`,
`xc-jdbc-prepared`, `xc-password-hash-verify` (2 findings),
`xc-ssrf-allowlist-fetch`, `xc-strict-json-body`,
`xc-tz-aware-scheduling` (2 findings).
