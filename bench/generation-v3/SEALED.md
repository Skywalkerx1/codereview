# SEALED — generation-v3 evaluation sets (B2 registered confirmation)

**Sealed:** 2026-11-05 · **Cases:** 88 (clean 64, defects 24) ·
**Manifest:** `SEALED-MANIFEST.json`
(sha256 `35bea8029e94fbda7bf961f646325cab5b5baa5287634a07a6b6638852b40690`;
per-file sha256 in the manifest, from committed blobs at source
commit `0e3bf464d930b48e4d89be64e90e2029b84a271d`)

## Seal rules (binding)

- These sets are **evaluation-only**. No case in them may be used
  to tune prompts, rubrics, thresholds, routing, policy, or seats.
  Policy work happens on the declared dev sets.
- **Burn rule:** one registered confirmation attempt per set. If
  the attempt fails its thresholds, these sets become dev data and
  a NEW sealed set must be assembled before any further attempt.
- Any change to a file listed in the manifest changes its hash and
  voids the seal. The labels below were fixed before the B2
  confirmation exists; nothing here has been run through any model
  panel, generation, or scoring.

## Counts

| Stratum | Sub-label | Cases |
|---|---|---|
| clean-authored | authored clean, test-validated | 56 |
| clean-realworld | real-world clean, 90-day no-fix (weaker label) | 8 |
| defect-injected | injected, fail-then-fix proven | 14 |
| defect-realworld | ground truth = real fix commit | 10 |
| **Total** | | **88** |

Defect categories: security 10, correctness 8, reliability 4,
data-loss 2 (one blocker, the rest major). Clean cases carry
`expected: []` by construction and by loader check.

## Construction — seven authoring tracks + coordinator

- **clean-authored ×4 tracks** (state & storage; money & data;
  time/concurrency/retry; web/IO boundaries), 14 cases each.
  Every case is a new, self-contained stdlib-only Python module
  presented as an added-file diff, with the intended behaviour —
  including edge-case contracts — stated in its docstrings, and a
  behavioural check (`validation/<id>/check.py`) that passes on
  the case's own code. This validation bar exists because of the
  A1 lesson: the previous expanded-clean set, authored without
  executable checks, let 18 real defects into "clean" cases.
- **clean-realworld ×1 track** (8 cases): real merged bug-fix
  changes from public projects presented as the change under
  review (the fix is the diff; the label is clean). Each fix
  commit predates the seal by ≥90 days with standing verified
  (fixed code present verbatim in the installed Python 3.12
  stdlib, in the project's current master, or in later release
  changelogs — per-case evidence in the track's work): CPython ×7
  (json/tool, random, textwrap, urllib/robotparser ×2, statistics,
  logging) and more-itertools ×1. Each ships a passing behavioural
  check mirroring the project's own regression test. Dropped
  candidates and their reasons (reverted fixes, fix-forwards,
  security fixes that would twin with defect cases) were recorded
  by the track; none were softened into the set.
- **defect-injected ×1 track** (14 cases): each case was built
  fixed-first — the correct file lives in
  `validation/<id>/fixed/` and the check passes against it — then
  exactly one behavioural defect was injected into the diff.
  Validation mode: the check FAILS on the case code and PASSES on
  the fixed overlay, so the pre/post pair defines the label.
- **defect-realworld ×1 track** (10 cases): ground truth is a
  real fix commit; the diff reconstructs the PRE-FIX code as a
  standalone module (stated in each case's `source`). Five from
  this repository's own history (fix commits ae422ea, 02bf9c0,
  2648231 — its code change is in probes/records_scan.py — 8deee7a,
  64cb223; checks adapted from each fix's own regression tests)
  and five from public CVE fix commits (CVE-2023-24329,
  CVE-2019-9740, CVE-2024-23334, CVE-2019-9636,
  CVE-2022-29217). One substitution is recorded in its case's
  `source`: the brief's suggested CVE-2020-8492 proved on
  verification to be a ReDoS, not the described CRLF defect, so
  CVE-2019-9740 (the actual CRLF mechanics) was used instead.
  Every case's check fails on the case code at the defect
  assertion.
- **Coordinator** (this seal): built the validation harness and
  manifest tooling, ran the central verification below, and
  assembled this seal. No case content was authored by the
  coordinator, and no semantic tuning judgement was applied to
  any case.

## Validation evidence (all at source commit 0e3bf46)

- Behavioural harness `validation/run_validation.py`:
  **88/88 cases validate, on two consecutive full runs.**
  Modes: clean 64 × check-must-pass; defect-injected 14 ×
  fail-then-fix-passes; defect-realworld 10 ×
  check-fails-on-defect. Per-case results:
  `validation/results.json` (hash-sealed with the validation
  files in the manifest).
- The product's own loader, unchanged, loads the set:
  `src/codereview/bench.py load_corpus('bench/generation-v3')`
  → 88 cases, manifest agreement verified, every case passes
  `load_case` validation (id shape, required fields, split,
  expected-entry vocabulary).
- Mechanical audits by the coordinator: every defect case has
  exactly one expected defect; every expected `line` lies inside
  its post-image file; no clean case carries an expected defect;
  no case id collides with any consumed set (corpus,
  expanded-clean, real-world — directory-name comparison only).
- Repository test suite at the seal commit: 1240/1240 OK.

## Who has seen these sets

- The seven authoring tracks above — each saw only its own cases
  plus the shared authoring spec.
- The set-build coordinator — harness runs and the mechanical
  metadata audits listed above; no semantic review of case
  contents, no tuning use.
- The parent/main agent has **not** read case contents.
- Nobody has run any case through a model, a panel, generation,
  or scoring. First contact with a model is the registered
  confirmation itself (Step 6).

## Scope and limitations (stated plainly)

- **Python only.** The validation bar requires executable
  behavioural checks; this sandbox has no JDK or Go toolchain, so
  no Java/Go cases are included (the consumed sets had both, and
  their Java cases could not be probe-verified either).
- clean-realworld is a **weaker label** than clean-authored: it
  rests on 90-day standing of a public fix, not on this set's own
  pre-registration adjudication. Scoring must report the two
  clean sub-labels separately (the `stratum` field carries the
  distinction in case.json, the corpus manifest, and this seal).
- Real-world defect cases are faithful-logic reconstructions of
  pre-fix code, not verbatim upstream files — the house style of
  the previous real-world stratum, stated per case in `source`.

## Case inventory

| Case | Stratum | Category | Expected | Title |
|---|---|---|---|---|
| v3c-io-bounded-reader | clean-authored | clean | 0 | Bounded response reader raises on oversize bodies and invalid UTF-8 |
| v3c-io-chunk-assembler | clean-authored | clean | 0 | Chunk assembler verifies SHA-256 manifest and writes only on full success |
| v3c-io-client-ip | clean-authored | clean | 0 | Client IP is the first untrusted address from the right, only via trusted peers |
| v3c-io-content-disposition | clean-authored | clean | 0 | Content-Disposition filename prefers RFC 5987 filename* with safe fallback |
| v3c-io-cookie-matching | clean-authored | clean | 0 | Cookie matching honours host-only flags, dot boundaries and path scope |
| v3c-io-filename-sanitizer | clean-authored | clean | 0 | Download filename sanitizer strips paths, reserved names and overlength |
| v3c-io-gzip-cap | clean-authored | clean | 0 | Gzip decoder aborts as soon as decompressed output exceeds the cap |
| v3c-io-header-injection-guard | clean-authored | clean | 0 | Email header builder rejects CR/LF but passes ordinary unicode |
| v3c-io-html-to-text | clean-authored | clean | 0 | HTML-to-text extractor skips script/style, decodes entities, breaks blocks |
| v3c-io-redirect-follower | clean-authored | clean | 0 | Redirect follower strips Authorization cross-host and refuses loops |
| v3c-io-request-id | clean-authored | clean | 0 | Request IDs propagate only when they match the safe charset and length |
| v3c-io-safe-path-join | clean-authored | clean | 0 | Safe path join refuses traversal, absolute and backslash escapes |
| v3c-io-upload-type-guard | clean-authored | clean | 0 | Upload guard requires declared content type to match magic bytes |
| v3c-io-url-canonicalizer | clean-authored | clean | 0 | URL canonicalizer lowercases scheme/host, drops default ports, sorts query |
| v3c-md-bill-splitter | clean-authored | clean | 0 | Even bill split in cents with deterministic remainder |
| v3c-md-bulk-upsert | clean-authored | clean | 0 | Bulk upsert with explicit conflict column policy |
| v3c-md-config-parser | clean-authored | clean | 0 | INI-style config with defaults and typed getters |
| v3c-md-csv-importer | clean-authored | clean | 0 | Strict all-or-nothing CSV inventory importer |
| v3c-md-cursor-pagination | clean-authored | clean | 0 | Stable cursor pagination over identical timestamps |
| v3c-md-duration-parser | clean-authored | clean | 0 | Duration parser to seconds |
| v3c-md-guarded-batch-delete | clean-authored | clean | 0 | Guarded batch delete with tenant filter, dry-run and cap |
| v3c-md-invoice-totals | clean-authored | clean | 0 | Invoice totals with per-line half-up tax rounding |
| v3c-md-jsonl-reader | clean-authored | clean | 0 | All-or-error JSON Lines reader |
| v3c-md-log-parser | clean-authored | clean | 0 | Log parser with continuation-line grouping |
| v3c-md-money-minor-units | clean-authored | clean | 0 | Money conversion to minor units with currency precision rules |
| v3c-md-price-parser | clean-authored | clean | 0 | Strict non-negative price parser |
| v3c-md-refund-proration | clean-authored | clean | 0 | Refund proration by largest remainder |
| v3c-md-semver-comparator | clean-authored | clean | 0 | Semantic version comparator with prerelease rules |
| v3c-st-audit-log | clean-authored | clean | 0 | Append-only audit log with size rotation keeping exactly N backups |
| v3c-st-config-snapshots | clean-authored | clean | 0 | Versioned config snapshots retaining only the newest five |
| v3c-st-csv-ledger | clean-authored | clean | 0 | CSV ledger writing its header exactly once across appends |
| v3c-st-file-cache | clean-authored | clean | 0 | Checksum-verified file cache with temp download and rename promotion |
| v3c-st-flag-store | clean-authored | clean | 0 | Feature-flag store with atomic JSON persistence and corrupt-file failure |
| v3c-st-job-guard | clean-authored | clean | 0 | Singleton job guard with atomic heartbeat lease and TTL boundary |
| v3c-st-kv-compaction | clean-authored | clean | 0 | Key-value file store whose compaction keeps only live keys |
| v3c-st-monotonic-counter | clean-authored | clean | 0 | File-backed monotonic counter under lock with fsync |
| v3c-st-session-store | clean-authored | clean | 0 | In-memory session store expiring on a monotonic clock |
| v3c-st-sqlite-settings | clean-authored | clean | 0 | SQLite settings repository with WAL, busy timeout and upserts |
| v3c-st-upload-offsets | clean-authored | clean | 0 | Resumable-upload tracker returning the first missing offset |
| v3c-st-upload-staging | clean-authored | clean | 0 | Upload staging with quarantine, validation and promotion |
| v3c-st-work-queue | clean-authored | clean | 0 | Directory work queue with atomic-rename claiming and delete ack |
| v3c-st-worker-heartbeat | clean-authored | clean | 0 | Worker heartbeat file with atomic refresh and age boundary |
| v3c-tc-bounded-pool | clean-authored | clean | 0 | Bounded worker pool rejects on full and drains on shutdown |
| v3c-tc-circuit-breaker | clean-authored | clean | 0 | Circuit breaker opens on consecutive failures and admits one probe |
| v3c-tc-deadline | clean-authored | clean | 0 | Monotonic deadline with clamped remaining and chunk checks |
| v3c-tc-debouncer-maxwait | clean-authored | clean | 0 | Debouncer coalesces calls but never exceeds max-wait |
| v3c-tc-health-aggregator | clean-authored | clean | 0 | Health aggregator isolates hanging checks and reports worst status |
| v3c-tc-idempotent-recorder | clean-authored | clean | 0 | Idempotent order recorder creates exactly one entry per key |
| v3c-tc-job-queue-visibility | clean-authored | clean | 0 | Job queue with visibility timeout and permanent ack |
| v3c-tc-lease-fencing | clean-authored | clean | 0 | Lease manager with strictly increasing fencing tokens |
| v3c-tc-next-run-dst | clean-authored | clean | 0 | Daily 09:30 next-run computation correct across DST gap and overlap |
| v3c-tc-retry-backoff | clean-authored | clean | 0 | Retry with jitter bounded by cap, deadline, and transient-only retries |
| v3c-tc-singleflight | clean-authored | clean | 0 | Singleflight executes once per key and never caches exceptions |
| v3c-tc-token-bucket | clean-authored | clean | 0 | Thread-safe token bucket refilling by monotonic elapsed time |
| v3c-tc-ttl-cache-grace | clean-authored | clean | 0 | TTL cache serves stale only inside the explicit grace window |
| v3c-tc-webhook-signature | clean-authored | clean | 0 | Webhook HMAC verification in constant time with replay window |
| v3d-batch-delete-tenant | defect-injected | data-loss | 1 | Retention purge deletes other tenants' rows |
| v3d-cache-key-user | defect-injected | security | 1 | Cache key omits the user, serving one user's payload to another |
| v3d-charge-idempotency-order | defect-injected | correctness | 1 | Charge runs before its idempotency record exists, so a retry double-charges |
| v3d-csv-formula-export | defect-injected | security | 1 | CSV export writes formula-leading user fields verbatim |
| v3d-daily-recurrence-dst | defect-injected | correctness | 1 | Daily 09:00 job drifts an hour across the spring DST transition |
| v3d-decode-latin1-fallback | defect-injected | correctness | 1 | Decoder silently falls back to latin-1 on invalid UTF-8 |
| v3d-download-path-traversal | defect-injected | security | 1 | Download path built by string concatenation allows ../ escape |
| v3d-money-float | defect-injected | correctness | 1 | Invoice total drifts a cent on half-cent values |
| v3d-pagination-cursor-tiebreak | defect-injected | correctness | 1 | Pagination cursor without an id tiebreak skips rows with tied timestamps |
| v3d-redirect-header-leak | defect-injected | security | 1 | Redirect to another host forwards the Authorization header |
| v3d-response-size-cap | defect-injected | reliability | 1 | Upstream response body is read into memory with no size cap |
| v3d-retry-unbounded-create | defect-injected | reliability | 1 | Create operation is retried forever with uncapped backoff |
| v3d-tax-rounding-half-up | defect-injected | correctness | 1 | Tax quantise silently uses bankers rounding instead of half-up |
| v3d-token-expiry-tz | defect-injected | correctness | 1 | Expired UTC tokens stay valid when compared to a naive local clock |
| v3r-json-tool-utf8 | clean-realworld | clean | 0 | JSON pretty-printer opens its files with an explicit UTF-8 encoding |
| v3r-logging-adapter-merge-extra | clean-realworld | clean | 0 | LoggerAdapter with merge_extra=True tolerates a missing extra on either side |
| v3r-numeric-range-slicing | clean-realworld | clean | 0 | numeric_range slicing resolves slices with slice.indices() so reversed and negative-step slices work |
| v3r-random-randbelow-mro | clean-realworld | clean | 0 | Random subclass picks its integer generator from the nearest MRO definition of random()/getrandbits() |
| v3r-robotparser-decimal-digits | clean-realworld | clean | 0 | robots.txt Crawl-delay and Request-rate silently ignore non-decimal digits instead of aborting the parse |
| v3r-robotparser-normalize-urls | clean-realworld | clean | 0 | robots.txt rule matching normalises percent-encoding without conflating raw ?, = and & with %3F, %3D and %26 |
| v3r-statistics-inf-nan-stdev | clean-realworld | clean | 0 | stdev and pstdev raise ValueError when the data contains infinity or NaN |
| v3r-textwrap-trailing-space | clean-realworld | clean | 0 | Text wrapper leaves no trailing space when a long word follows an exactly-full line |
| v3w-aiohttp-static-traversal | defect-realworld | security | 1 | Static-file resolver skips root containment entirely when follow_symlinks is enabled |
| v3w-attempt-rows-malformed | defect-realworld | reliability | 1 | One malformed telemetry row aborts the whole records scan |
| v3w-discovery-duplicate-seat | defect-realworld | correctness | 1 | Setup merge seats an exact duplicate of a discovery pick |
| v3w-error-detail-presence | defect-realworld | data-loss | 1 | Persisted report entry drops a present-but-falsy error_detail block |
| v3w-incomplete-capture-marker | defect-realworld | reliability | 1 | Partial sandbox capture is presented as whole when a detached process holds the pipe |
| v3w-migrations-whitespace-pattern | defect-realworld | security | 1 | Migration-risk pattern misses destructive SQL written with non-space whitespace |
| v3w-pyjwt-hmac-key-confusion | defect-realworld | security | 1 | HMAC key preparation accepts asymmetric public keys as HMAC secrets, enabling algorithm confusion |
| v3w-urllib-query-crlf | defect-realworld | security | 1 | Request-target validation checks the path but not the query, allowing CRLF header injection |
| v3w-urlsplit-leading-blank | defect-realworld | security | 1 | URL parser misses the scheme of a URL prefixed with blank characters, defeating scheme blocklists |
| v3w-urlsplit-nfkc-netloc | defect-realworld | security | 1 | Hostname parser accepts netloc characters that NFKC-normalize into URL separators |
