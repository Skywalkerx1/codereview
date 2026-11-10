# Changelog

## 0.13.3 — MCP policy-trust removal — 2026-11-10

Closes the remaining item from the 0.13.2 audit line (item E,
owner ruling 2026-11-10), plus the path-root restriction from
the external review of 2026-11-10:

- The MCP `run_gate` tool no longer accepts policy trust from
  the caller. The `trust_repo_policy` argument is removed
  from the tool (passing it is now refused as an unknown
  argument, before anything runs), and a `policy` path that
  points inside the reviewed repository is refused for the
  same reason: an explicitly named policy is honoured in
  full, so naming the repo's own `.codereview.toml` defeated
  the P3-01 trust restriction. That file is still discovered
  and applied in restricted form — strengthening keys only,
  dropped keys returned as `policy_ignored_keys`.
- A policy a caller names through `run_gate` is now ALWAYS
  applied in that same restricted form, wherever the file
  lives (owner-approved route (b), 2026-11-10): the run's
  record shows origin `mcp-caller`, hooks never run, and
  every gate-weakening key is dropped and named in
  `policy_ignored_keys`; path rules keep working. A named
  policy that does not exist is refused before anything
  runs. Full trust through the server is reserved for the
  operator, at server start: `codereview mcp serve
  --policy FILE` (or `$CODEREVIEW_MCP_POLICY`), read once;
  when one is set it governs every run and a caller-named
  policy is refused, never an override. Full trust in a
  repository policy also remains available where it
  belongs: the local CLI's `--policy` /
  `--trust-repo-policy`, run by the operator.
- The MCP server can now pin caller-supplied paths to an
  operator-approved root: `codereview mcp serve --root DIR`
  (or `$CODEREVIEW_MCP_ROOT`). The `repo`, `out`, and
  `record` arguments of both tools must then resolve inside
  that root (checked on the resolved path, so a symlink
  pointing outside is refused too); anything outside is
  refused before it runs or is read. With no root
  configured, path handling is exactly as before, and the
  server prints one stderr notice at startup saying so and
  naming how to set a root.
- Apart from the MCP serve flags above (and the CLI's new
  `--policy-restricted`, which the server passes for
  caller-named policies), the CLI, the policy engine, and
  the verdict payload's policy-visibility fields are
  unchanged.

## 0.13.2 — security patch line — 2026-11-07

Fixes from an AI-driven audit of the MCP server surface, run
with the Cloud Security Alliance's published mcpserver-audit
prompts (outputs triaged 2026-11-07):

- Full-file context and builder-supplied `context` are now
  redacted with the same secret redaction as the diff before
  they reach reviewer prompts or the run record. Previously
  only the diff was redacted, so a secret on an unchanged
  line of a touched file, or one pasted into the change
  description, was sent to providers in clear text.
- The verification round's builder response and
  test-command output are redacted the same way before they
  reach reviewer prompts or the run record; a failing test
  that echoes config or environment no longer puts a secret
  into either.
- The MCP `run_gate` tool's `context` argument is literal
  text: a leading `@` is no longer read as a local file
  path on the MCP path, and the value is forwarded in the
  `--context-literal=VALUE` form so text beginning with
  `-` is accepted as text too. The CLI's own
  `--context @file` behaviour is unchanged.
- `codereview report` and `support-bundle` under
  `--no-records` now leave crash notes out as well, as
  PRIVACY.md already stated.
- Authenticated custom providers now require an https://
  base URL; http:// remains allowed for loopback hosts.
  Keyless local providers are unchanged.
- Record writes use an unpredictably named temp file
  (mkstemp) instead of a pid-derived name, so a pre-planted
  symlink at the temp path is never followed.
- The MCP `get_verdict` output labels its summary
  `unverified`: it reads a stored record back without
  re-verifying it.

## 0.13.1 — 2026-11-07

- Metadata-only release: PyPI landing page; no code change.
  The 0.13.0 upload's hand-rolled form post omitted the
  metadata fields PyPI builds the project page from, so the
  page showed no description. 0.13.1 switches the package
  readme to the short `PYPI-README.md` landing page (the
  long README stays the GitLab front page). Gate code,
  claims text and figures are unchanged from 0.13.0.
- README "Status" paragraph refreshed (it still described
  the v0.4 line); no claims or figures changed.

## Unreleased — C1 claim correction + profile-attribution lint (2026-11-07)

- **Corrected (defect C1, found by the external tester's
  verification pass):** the README lead paragraph attributed
  the `balanced` profile's registered attempt-1 figures
  (precision 0.875; clean-BLOCKED 22/34 = 0.647, quoted as
  "65%") to the default `strict` gate, and cited a record
  that measured neither. The paragraph now states `strict`'s
  own paired row from the same records — recall 1.00 (7 of 7),
  merged blocking precision 0.583, clean-BLOCKED 32 of 34
  (0.941), each with its Wilson 95% interval — and cites the
  attempt-1 results record,
  `bench/generation-v2/RESULTS-2026-11-05.md`.
  `bench/CLAIMS-SHEET.md` carries
  the paired-`strict` row as a governed claim, with the
  precision derivation stated.
- The claim lint now checks profile attribution (W0): a
  paragraph that states one profile's recorded figure while
  naming only a different profile — and never the profile of
  record in the paragraph or its section — fails. The
  original C1 sentence is pinned as a mutation test.

## Unreleased — L19 collector endpoint live (2026-11-07)

- The feedback collector endpoint is set (`feedback.ENDPOINT`
  → `https://phpatch.com/codereview/report`). The receiving
  service is a small standalone collector on the project host:
  POST-only, the client's own size caps enforced server-side,
  payloads stored under server-generated names and purged
  automatically after 90 days per PRIVACY.md. `report` and the
  opt-in crash ping are live channels now; the manual
  support-bundle route remains available.
- PRIVACY.md retention wording aligned to the live service
  (90 days, maintainers-only access, automatic purge, deletion
  on request via support@phpatch.com).
- `CODEREVIEW_RELEASE_CHECK=1` is green with this build.

## Unreleased — final build candidate: positioning copy + launch placeholders (2026-11-07)

- Positioning copy (owner-approved exact text) is the README
  lead and intro, and the setup wizard's opening line.
- Launch placeholders filled: security contact
  `support@phpatch.com` with a 5-working-day acknowledgement
  target; privacy / deletion contact `support@phpatch.com`,
  retention 90 days, access limited to the maintainers;
  `[project.urls]` and the report command's tracker URL point
  at the live GitLab project. Provider-family label in the
  crash ping: none (the spec default — the ping carries no
  provider field).
- Deliberately NOT set: the feedback collector endpoint
  (`feedback.ENDPOINT`). No receiving service exists yet;
  `report` and the crash ping stay inert and the manual
  support-bundle route is the live channel until the owner
  stands one up (it needs its own security review — see the
  L19 request). `CODEREVIEW_RELEASE_CHECK=1` flags exactly
  this one remainder.

## Unreleased — crash handling and user feedback (L17–L19)

- **L17 — crash handling.** `codereview` now runs under a top-level
  guard (`console_main`). An internal error prints one line, writes
  a redacted `codereview-crash-*.json` note (mode 0600) and exits
  **2**, never 0 or 1. `--debug` / `CODEREVIEW_DEBUG=1` adds the
  redacted traceback. Ctrl-C exits 130; a closed pipe exits 141
  quietly. A crashed `pr --post` run sets the commit status to
  *pending*, never *success*.
- **L18 — bug reports.** `codereview support-bundle` writes one
  redacted zip (identity, package list, environment variable
  *names*, redacted config and policy, latest record, crash notes,
  MANIFEST). Per-file and total caps; anything left out is listed.
  `codereview report` shows the contents and sends only after
  confirmation, over HTTPS (http only to loopback), without
  following redirects. No endpoint is built in; the owner sets one.
- **L19 — feedback.** Optional anonymous crash ping, off by
  default (`codereview telemetry enable|disable|status`), fixed
  field list, one per crash signature per day, 3 s timeout, never
  changes the exit code. `CODEREVIEW_TELEMETRY=0` overrides.
  See `PRIVACY.md`, `SECURITY.md`, `CONTRIBUTING.md`.
- Owner must set before launch: collector endpoint, security and
  privacy contacts, retention text, public tracker URL
  (`CODEREVIEW_RELEASE_CHECK=1` lists what is left).

## Unreleased — post-RC fixes from the L6 source review (2026-11-07)

The external tester's L6 source review of the 0.13.0 release
candidate (`69d1c65`, verdict NOT READY) found defects in code
the earlier phases never exercised. All are fixed here; none
is a regression from 0.12.1.

- **L6 F1/F2 (S1) — the probe tree copy dereferenced
  symlinks.** `run_probe` copied the reviewed tree without
  `symlinks=True`, so a planted link was replaced by its
  target's content inside the sandbox copy (pulling any host
  file the operator can read into the probe tree), a dangling
  link made the copy raise out of `run_probe` — silently
  losing every probe on such a repo — and a link to a special
  file streamed its content into the copy in the parent
  process, unbounded. The copy now preserves links (parity
  with `evidence._copy_tree`), and a copy failure returns an
  `error` probe outcome instead of raising.
- **L6 F3 (S2) — a non-JSON 2xx reply lost the finished
  review.** `post_review`/`set_status` parsed the response
  body unguarded; an HTML 200 (captive portal, proxy) raised
  `JSONDecodeError` past `review_pr`'s `GitHubError` handler,
  so the CLI died with a traceback and wrote no record. An
  unparseable POST body now raises `GitHubError`, which
  `review_pr` records in the report.
- **L6 F4 (S3) — `parse_pr_url` accepted malformed URLs.**
  The pattern was not end-anchored (`…/pull/12abc` parsed as
  PR 12) and owner/repo admitted `?`, `#`, `%` into the API
  path. Owner/repo are now `[\w.-]+` and the number must end
  the URL (one trailing slash allowed); suffixed URLs such
  as `/pull/12/files` are rejected, not silently truncated.
- **L6 F5 (S3) — the auto-stem choice in `write_report` was
  still racy.** The P6-02 exists-check let two processes in
  the same second both pick a free stem, the later
  `os.replace` silently overwriting the earlier record. The
  chosen auto stem is now claimed with an `O_EXCL` claim
  file for the duration of the write; explicit stems (the
  caller's contract) are never claimed or renamed.
- **L6 F5 rerun (S2, re-rated by the tester) — the claim
  protocol still had a window.** Her rerun reproduced the
  RC losing records (15/15 trials) and the claim build clean
  on her machine (0/15) — but the race is timing-dependent,
  and here the claim build lost records too (up to 4/15 bad
  trials): a rival can claim, write AND release entirely
  inside the window between our exists-check and our claim
  landing, after which our claim succeeds on a stem whose
  record pair now exists and the write overwrites it. The
  pair is now re-validated under the claim; a stem whose
  pair appeared since the check is yielded, never
  overwritten. Pinned by a deterministic interleaving test
  plus her `f5_race.py` (90/90 trials clean after the fix).
- **L6 rerun S3 — `verify_record` mis-described fresh
  patch-mode records.** A record with no range/head was
  always explained as "predates range/head tracking
  (v0.7.3)"; a record stamped by a build that has the
  tracking (v0.7.3+) but carrying no range is a patch-mode
  run, and now says "no range recorded (patch mode)". Only
  genuinely pre-tracking (or unversioned) records keep the
  age explanation.
- **Tests/tooling from the same rerun:** a
  mutation-gap pin set for `_apply_gate_profile` /
  `_evidence_class` (her partial mutation pass: 14 of the
  first 30 mutants survived, concentrated in those two
  functions), and `bench/scripts/check_archive_suite.py`,
  which runs the suite from the built delivery archive so a
  count is always measured on the artefact that ships.
- **Rerun-2 mutation pins (tests only, no behaviour
  change):** her completed mutation pass over `22055d1`
  left 13 of 106 mutants standing. The ones she marked
  worth pinning are now pinned in
  `tests/test_profile_mutation_gaps.py` and verified
  killed under her own harness: `_reviewer_tasks`
  lens-seat pins (mutants 32–35), the `assess_panel`
  detail family list (56, 57) and the
  `escalation_triggers` failed-reviewer naming (93).
  Mutant 54 (`min_families > 0` → `>= 0`) is equivalent —
  the second conjunct is false at 0 — and the `risk.py`
  boundary mutants (68, 81, 84, 86) and the `_gate`
  `allow_major` default (19) remain open as low-value /
  equivalent, as she read them.

## 0.13.0 — 2026-11-07

First release candidate of the 0.13.0 line. Everything the
0.13.0.dev0 development window accumulated (the external
tester's Phases 2–6 follow-ups, the Epic K/L surfaces, the
B3 prerequisites) is collected in the subsections below,
followed by the release-candidate prep batch that closes
the tester's standing must-fix queue (release-gate items
L8, L10, L11, L13, L15, L16). The default gate profile
remains `strict`; the B2 registered confirmation ran on
2026-11-06 and FAILED its primary threshold, and B3 remains
design-only — no claim in this release rests on either.
PyPI publication stays on the owner's hold: this release
exists as a git tag and mirror state, not a package-index
upload.

### Release-candidate prep — L8, L10, L11, L15, L16 (2026-11-07)

- **L8 (P3-03 residual) — the bare PEM body shape.**
  `redact_secrets` now redacts a standalone PEM body line
  that carries a key's DER/OpenSSH start (a diff hunk that
  starts mid-key has no header line). Redaction coverage
  26/32 → 27/32 shapes; the five transformed forms remain
  the accepted residual, and README + THREAT-MODEL now
  state the encoded-form boundary plainly.
- **L10 (P3-12 / NT9) — the notifier's process group dies
  with it.** The summary cap half already landed with
  P3-12 (500 chars, argv and record). The runner now starts
  the command in its own session under a supervised wait
  and kills the whole process group on timeout — and
  sweeps it on normal exit (the P3-06 rule) — instead of
  `subprocess.run`'s direct-child-only kill.
- **L11 (P3-04 residual) — hardening inside `collect()`.**
  `evidence.collect` applies the process hardening at its
  own entry, so direct library use carries the same
  /proc-environ protection as the CLI path by construction
  (the `_execute` backstop stays). Sibling-process
  exposure remains residual 7, documented and warned.
- **L15 — the superseded naive precision figure is no
  longer quoted in shipped prose.** It appeared, always
  marked superseded, in `bench/README.md`,
  `bench/PUBLIC-BENCHMARK.md` §5, `bench/CLAIMS-SHEET.md`
  and this CHANGELOG's 0.12.0 entry; all four now refer to
  it by description and point to the corrected counting.
  It survives only in the registered baseline records
  (immutable history) and in the claim lint's detection
  fixture.
- **L16 — no B2/B3-derived claims; the stale confirmation
  status is corrected.** Shipped docs no longer say the B2
  confirmation "has not run": README, PUBLIC-BENCHMARK
  §3.5 and CLAIMS-SHEET now record the registered FAIL
  (blocking-tier recall 7/24 against ≥ 0.60; clean-BLOCKED
  6/64 passed; default stays `strict`), and B3 is
  described only as design-only and unconfirmed.

### L3 smoke fix — the gpt-5 family takes `max_completion_tokens` (2026-11-07)

Folded in from the L3 real-system smoke's first pass: the
`openai` provider preset's default model (gpt-5-mini) could
not serve through the CLI at all — the provider layer sent
`max_tokens`, which the gpt-5 family rejects (HTTP 400; it
requires `max_completion_tokens`), so the seat errored and
the run degraded; the same seat passed with the documented
`openai:gpt-4.1` override. Fix: a per-preset
`completion_tokens` quirk table in the registry (the
gpt-5 / o-series prefixes on the `openai` preset, empty
elsewhere), wired through the seat factory beside the
existing temperature quirk — those models now send the cap
as `max_completion_tokens`; every other model keeps
`max_tokens`. Pinned by a payload test per model family
(no live call). The B2 confirmation's gpt-5.4 seat was
unaffected: the bench `llm_chain` path builds its own
payloads.

### THREAT-MODEL: accepted record-integrity limit stated; probe paragraph corrected (2026-11-07)

Phase 6 rerun 4 verified P6-12b fixed on `35f6043` and
closed release-gate item L1 on that build. The tester's
acceptance of the consistent-forgery variants (G2/G3/G4)
was conditioned on the accepted limit being stated in
THREAT-MODEL (gate item L12); this entry makes that doc
change, and corrects one stale paragraph the same
read-through exposed.

- **New residual 13 in `THREAT-MODEL.md`.** The record
  content hash is edit detection, not a signature: it
  detects edits to any record that carries one, and
  verification fails closed on stamping-era or garbled
  declarations — but a record whose declarations are
  rewritten to look pre-stamp is indistinguishable from a
  genuine pre-stamp record, is accepted as legacy, and
  edits to it are not detected. Accepted limit, stated in
  the threat model in the tester's terms.
- **Probe trust-boundary paragraph corrected.**
  `THREAT-MODEL.md` still said Tech Lead probes set no
  rlimits and kill only the direct child on timeout; the
  C5 hardening (2026-11-06) set rlimits and a process-group
  kill in `probe.py`, so the paragraph now describes the
  sandbox as built. Documentation only — no code changed.

### P6-12b: legacy rule applies inside the pre-machinery shape (2026-11-07)

The Phase 6 rerun-2 scope boundary exempted any record
carrying no v1 machinery (`schema_version`, `provenance`,
`record_identity`) from the P6-12 provenance rule
categorically. Rerun 3 (the tester's `p6_downgrade3.py`)
showed the exemption was wider than stated: deleting
those three sections from a fresh 0.13.0 record — with a
planted blocker finding added — verified as a "legacy
record" even while the record still declared
`version: 0.13.0.dev0` (variant G6), and deleting all
five declarations verified on no evidence at all (G1).

- **The declarations rule now applies to the
  pre-machinery shape too.** `content_hash_required`
  reads the surviving declarations of every hash-less
  record under the same fail-closed rule: legacy needs
  at least one parseable pre-stamp declaration among
  `version`, `provenance.generator_version`,
  `created_at`, and no stamping-era or garbled one.
  G1 and G6 now fail verification; the consistent-
  forgery variants (G2/G3/G4 — forge every declaration
  pre-stamp) still pass, the documented not-a-signature
  limit, unchanged.
- **Genuine historical records are unaffected.** Every
  writer of the pre-schema era stamped `version` and
  `created_at` (the 0.9.4 / 0.9.6 historical fixtures
  carry both) and they keep the exemption on that
  evidence (pinned).
- **Pins.** `tests/test_phase6_fixes.py`: the rerun-2
  boundary pin asserted the all-five-deleted shape read
  legacy — that shape is G1, so it is replaced by G1/G6
  failure pins plus a genuine-pre-schema legacy pin
  (+2 net). The hand-built minimal records in
  `tests/test_solution_v073.py`,
  `tests/test_v093_phase2.py` and
  `tests/test_v095_fixes.py` carried no declarations at
  all — a shape no writer ever emitted — and now carry
  the pre-stamp `version`/`created_at` of their era;
  no assertion in them changed.
- **Release note — the 0.13.0 dev window (noted at the
  tester's rerun-3 request).** Unstamped records written
  by 0.13.0 dev builds between the 0.13.0 version bump
  (2026-11-06 19:16Z) and the content stamp landing
  (2026-11-07 02:07Z) do not read as legacy: their
  version line is stamping-era while their hash was
  never stamped. That closed set is dev artefacts only;
  registered and B2-era records predate the 0.13.0 line
  and are unaffected.

### probe sandbox C5 hardening (2026-11-06)

The B3 design's hard prerequisite (its §5.1, pass/fail row
P0): `probe.py`'s sandbox set no rlimits and its timeout
killed only the direct child, so a forked or backgrounded
probe process could outlive its budget. Probe execution
now meets the C5 discipline the evidence sandbox
established, as a standalone enforcement-only change:

- **Process-group kill.** The probe runs in its own
  session; expiry — and normal exit, so a probe that
  backgrounds a child and exits cleanly leaves nothing
  behind — kills the whole process group.
- **POSIX rlimits** (applied in the child): CPU time =
  wall timeout + 5 s, address space 2 GiB, per-file size
  256 MiB, open files 1024, core dumps off. The process
  count is deliberately not rlimited (a per-user ceiling
  the operator's uid shares); containment is the group
  kill plus the CPU/address-space limits.
- **Drained, capped output.** Reader threads drain both
  streams under an 8 MiB per-stream cap instead of
  `communicate()`'s unbounded buffering; a capture cut
  short by the cap or by a detached pipe-holder is marked
  in the output, never presented as whole.

Outcome vocabulary, the result contract, `probe_decision`,
`parse_probe_spec` and every gate profile are unchanged —
a limit-killed probe is an ordinary fail (its exit code is
the negative signal number), a timed-out probe an ordinary
timeout. Seven new pins in `tests/test_probe_harness.py`
cover the limits as observed from inside the probe, the
forked-child and backgrounded-child kills, the CPU and
memory ceilings, the file-size ceiling, and the output cap.

### B3 dev-pilot scaffolding (2026-11-06)

Mechanism-agnostic harness for the B3 dev pilot (design §8).
Scaffolding and data collection only: no new gate profile, no
probe-promotion decision, no prediction is computed or
registered — those wait on the owner's design approval and the
Q1 protocol ruling.

- **Probe channel wired into the bench pipeline (opt-in).**
  `bench.run_bench` accepts `probes=True` (or a config's own
  `"probes": true`) and passes a `probe.make_probe_fn` channel
  into `run_review` — the existing adjudication channel, bounded
  by `MAX_PROBE_ROUNDS`, able only to rebut. Probe outcomes are
  collected onto the result record (`probes_enabled`,
  `probe_outcomes`) as data; wiring the channel changes no
  verdict. Default OFF: the run_review call and the record
  shape are byte-identical to before (pinned by test), and a
  config's identity hash moves only when its probe opt-in is
  enabled.
- **New module `codereview.pilot`.** The §8 hash split
  (deterministic sha256 partition of case ids into calibration
  / evaluation slices) with a committed split manifest whose
  `inputs_sha256` binds salt + case set + rule, so a split
  cannot be re-rolled silently (`verify_split_manifest`); the
  §3.1/§3.2 eligibility screen (blocking tier + executable
  basis in the A5 taxonomy + the R4 concrete-trigger test,
  deterministic, basis recorded per finding); and the
  calibration-table builder — per case, findings with
  eligibility and probe outcomes, every current profile's
  verdict replayed through `core.evaluate_gate_policy`, and
  the §8 prediction factors (p_base / p_elig / p_settle) as
  raw input counts per slice. Inputs only: the prediction
  formula and its registration remain the pilot
  registration's step.
- **Pilot runner `bench/scripts/run_b3_pilot.py`** (preflight /
  run / table): writes the split manifest before anything runs,
  runs the dev sets (v1 public split + expanded stratum) live
  under a current profile with the probe channel optionally
  wired, and emits `calibration-table.json` in the documented
  `codereview.b3-calibration/1` format.

### 0.13.0.dev0 (external Phase 6 follow-up fixes)

Fixes from the external tester's Phase 6 report (end-to-end
journeys and non-functional tests, run against ebfa217;
2026-11-06), each re-verified against the current master —
P6-01 (the S1) was already fixed by the Phase 5 second-rerun
batch (atomic record writes) and her crash repro passes
clean:

- **Same-second runs no longer overwrite each other
  (P6-02).** The automatic record stem has one-second
  resolution; two runs in one second on the same `--out`
  silently replaced the first run's record. A taken auto
  stem now gains a counter suffix; explicit stems (the
  post-hooks rewrite contract) are never renamed.
- **record-verify detects hand-edited records (P6-03).**
  The writer stamps a content hash over the whole record
  (excluding the `record_identity` envelope) and verify
  recomputes it in single and chain mode — a flipped gate,
  a softened finding, forged test results all fail. The
  hash detects edits; it is not a signature (an editor
  who recomputes it passes). Records written before the
  stamp carry no hash and verify as legacy,
  not-applicable — never retro-failed.
- **Git-quoted paths resolve to their real names
  (P6-04).** Paths git C-quotes (non-ASCII, tab, quote)
  were attributed to the file `unknown`; the patch parser
  now decodes the quoted form everywhere paths are read
  (sections, added lines, line maps, patch stats), so
  per-file coverage, path rules and SARIF locations see
  the real path.
- **Escalated findings appear in the disputes inventory
  (P6-05).** A finding the Tech Lead escalated to the
  owner was in no open-dispute list: invisible in
  `codereview disputes` and passed over by
  `disputes --check`. `escalated` is now an open
  (human-decision) status there and in the record's own
  `open_disputes` summary; an owner disposition closes it.
- **Agent-CLI seats carry their CLI's vendor family
  (P6-06).** Every agent seat was family `agent`, so a
  Claude+Codex panel computed as one family and could
  never satisfy two-family release eligibility without a
  hand-written `--seat-meta`. Family now derives from the
  CLI a seat runs (claude → anthropic, codex → openai,
  gemini → google; unknown CLIs keep `agent`), and the
  setup wizard persists the seat metadata it derives
  (`[seat_meta]` in the user config), applied between
  the derived baseline and explicit `--seat-meta`.
- **The re-ground pass has a call budget (P6-07).**
  Re-grounding fanned out one model call per ungrounded
  finding (3,000 findings → 2,996 calls). The pass stops
  at `MAX_REGROUND_CALLS` (100); findings past the budget
  stay ungrounded with the budget named in their
  re-ground note and in the gate reasons.
- **`loop`'s surface is documented (P6-08).** The README
  and `loop --help` state what loop takes and what it
  does not (`--seat-meta`/`--policy`/`--role`), and why
  its per-round records — working-tree rounds with no
  committed range/head — are not Form B chain or release
  records. Docs only.
- **`on_blocked` names a seat state (P6-09).** The hook
  fires when a SEAT ends in a K2 blocked class, not when
  the gate verdict is BLOCKED; the docs now say so, and
  `[hooks]` accepts the additive alias key
  `on_seat_blocked` for the same slot. No rename; the old
  key keeps working.
- **Record JSON is written with sorted keys (P6-10).**
- **High-band evidence doctrine aligned (P6-11).** A
  high-band run with no evidence record supplied BLOCKS
  (required evidence *missing*); the docs now state the
  per-item distinction explicitly — a supplied record
  whose required item is *unavailable* is the
  INCONCLUSIVE branch. Code unchanged; a contrast pin
  covers the unavailable case.

Rerun addendum (the tester's Phase 6 rerun on the build
carrying the fixes above confirmed every Phase 6
disposition, and raised four new items — each re-verified
here before any change):

- **The legacy exemption is bounded by provenance
  (P6-12).** Deleting `content_sha256` from a freshly
  stamped record made record-verify report it as a legacy
  record and pass any edit. A record whose own
  declarations (generator version, creation time) place
  it in the stamping era must now carry the hash; its
  absence fails verification in single and chain mode.
  Records declaring pre-stamp provenance keep the legacy
  reading. The standing limit is unchanged: the hash
  detects edits, it is not a signature.
- **Hook commands are redacted in the record (P6-13).**
  A `[hooks]` command was stored verbatim in the record's
  hooks section, so a credential embedded in the command
  travelled with the artefact. Stored copies now pass
  through the same secret redaction as captured output;
  the executed command is unchanged.
- **The sdist ships the guarded docs (P6-14).** The
  claims sheet, the public benchmark doc, the pilot kit
  and the root roadmap/review notes are in the
  distribution, so the unpacked suite runs green and the
  claim lint guards the same doc set everywhere.
- **Cleanup pins are temp-isolated (P6-15).** The
  sandbox-cleanup tests diffed snapshots of the shared
  system temp dir and could fail on another process's
  sandbox; they now run against a private temp dir.

Rerun-2 addendum (the tester's second rerun confirmed
P6-13, P6-14 and P6-15 fixed, and showed P6-12 only
partly closed):

- **The legacy exemption now fails closed (P6-12,
  rerun 2).** The provenance bound trusted any one
  declaration and read missing or unparseable fields as
  pre-stamp, so stripping the hash plus deleting or
  garbling two fields passed an edited record as legacy
  (seven variants). All three declarations (version,
  `provenance.generator_version`, `created_at`) are now
  read and classified; legacy requires positive,
  consistent pre-stamp evidence, and a stamping-era,
  garbled or absent provenance fails verification in
  single and chain mode. Honest pre-stamp records keep
  the exemption. Records carrying no trace of the v1
  machinery at all (the pre-schema shape) stay
  not-applicable, as for every machinery-era check;
  reaching that shape from a current record means
  deleting its entire format layer, the documented
  wholesale-rewrite residual. One documented cost: unstamped records
  from 0.13.0 dev builds in the hours before the stamp
  landed no longer read as legacy. The standing limit is
  unchanged: the hash detects edits, it is not a
  signature.
- **Invalid escape fixed (rerun-2 nit).** The redaction
  stop-char literal spelled a backslash as an invalid
  escape sequence (a SyntaxWarning on Python 3.12+, an
  error under `-W error`); the set is unchanged, the
  spelling is now correct, and a compile pin holds it.

### 0.13.0.dev0 (external Phase 5 second-rerun fixes)

Fixes from the external tester's Phase 5 second rerun on
the fixed build 784ff95 (2026-11-06), each independently
verified against master. The rerun verified all four
previous residuals fixed; what remained was in the claim
lint, plus the write-atomicity remainder of P6-01 (the
same write path P5-07b hardened, fixed early ahead of the
Phase 6 follow-up):

- **Record writes are atomic (P6-01).** `write_report`
  wrote the final path in place: a write failing midway
  (file-size limit, disk full, a kill) left a truncated,
  invalid JSON record at the `--out` path — the P5-07b
  fallback net preserved the review, but a tool scanning
  `--out` still picked up the broken file. Both the JSON
  record and the Markdown report now land via a temp file
  in the same directory, fsync, and `os.replace`; on
  failure the temp is removed and the final path holds the
  previous file or nothing. The hooks' rewrite of the
  record (the record is rewritten at the same stem once
  the post-record hooks have fired) goes through the same
  writer, so a midway rewrite failure leaves the first,
  complete record intact.
- **Claim lint: six more evasions closed (P5-08c).**
  Paragraphs are matched NFKC-normalised, so full-width
  digits and letters can no longer disguise a figure;
  the pattern table gains the count-free all-of-set
  form, the spelled-out percent form, and the remaining
  perfection phrasings the second rerun tried; and the
  fraction rule accepts the spelled N-of-N form under
  the same local-context discipline. The guarded
  shipped docs pass unedited, and the tester's three
  lint scripts are now fully caught — the newest set
  went from four of ten caught to ten of ten.
- **The claim lint states its own limit (P5-08d).** The
  lint's docstring now says plainly that it is a phrase
  list — a tripwire over known phrasings, not a proof a
  document makes no unqualified claim — and that any new
  wording passes until it is added.

### 0.13.0.dev0 (external Phase 5 rerun fixes)

Fixes from the external tester's Phase 5 rerun on the fixed
build ebfa217 (2026-11-06), each independently verified
against master:

- **The `--out` check proves writability, and a late write
  failure keeps the review (P5-07b).** The Phase 5 up-front
  check inferred writability from `os.access`, which passes
  for a root user on `/proc` and `/sys`: the full review ran,
  then the report write crashed and discarded the result.
  Three prongs: (1) the check now proves the directory by
  creating the directory chain and a temp file for real,
  then removing them — a create fails for root exactly as
  for anyone else — so an unusable `--out` still refuses
  before any provider call; (2) independently, the report
  write is wrapped: an `OSError` after the review completes
  prints the verdict, writes the record to a fallback
  location (current directory, then temp directory, then
  stdout itself) and exits 2 instead of tracebacking;
  (3) the tests simulate the unwritable case by mocking the
  create, so they pass identically as root and non-root.
- **The PR reasons line carries no live Markdown (P5-04b).**
  Gate reasons are untrusted text (they can carry
  repo-policy-derived content), and the Phase 5
  neutralisation left bare URLs autolinking, `#N` and
  `owner/repo#N` forming cross-references, and
  reference-style links live. The rendering boundary now
  also breaks the scheme separator in bare URLs, splits
  the reference-link join, defuses line-start reference
  definitions, and breaks `#` before a digit.
- **Claim lint: wider scope, more phrasings (P5-08b).**
  The lint's doc set is now every shipped *.md in the tree
  (docs/, skills/, plugin and probe READMEs included),
  with records excluded by name and by tree under the same
  immutability rule as before; the pattern table gains the
  reversed-decimal, spelled-out, all-of-set and
  no-miss phrasing families the rerun evaded with, under
  the same same-paragraph qualification and local-window
  discipline.
- **SARIF `..` segments resolve (P5-01b).** The Phase 5
  normalisation dropped `..` segments, which could point a
  finding at a different file. Paths now resolve with
  `posixpath.normpath`; a path that still escapes the root
  after normalisation emits no location at all rather
  than a misleading one.
- **P5-14 recheck: not a defect.** The rerun's capture
  showed the herdr launcher's file-path message clipped;
  the literal in the launcher source is intact ("workspace
  path is not a directory") — the tester's harness cut the
  line. Pinned in the rerun regression tests so the
  wording cannot silently regress.

### 0.13.0.dev0 (external Phase 4 rerun fixes)

Fixes from the external tester's Phase 4 rerun on the fixed
build (2026-11-06), each independently verified against
master. The fix implementations for the four code items were
adopted from the tester's own solution patch (p4-residuals),
with completions noted:

- **Torn JSONL tails are removed before appending
  (P4-08b).** The P4-08 read tolerance left the torn bytes in
  place: the first resume appended after them, and the
  second resume crashed on the fragment turned corrupt
  mid-file line. Before the generation/attempt/journal
  append handles open, a torn final line is now dropped
  (temp file + fsync + atomic replace) and an unterminated
  parseable final line gains its newline; when dropping the
  tail would expose another invalid line, the file is left
  untouched — real damage still raises on read.
- **Provider and seat error text is redacted before it can
  reach a record (P4-01b).** The P4-01 error-body excerpt
  entered the ProviderError message unredacted, and that
  message is persisted verbatim into records and reports —
  a 401 body quoting the caller's own key back leaked it.
  The excerpt now passes through `redact_secrets` before
  truncation (class-deciding text such as
  `insufficient_quota` survives); if redaction itself fails
  the excerpt is dropped and the status kept. Audit
  extension: an agent seat's stderr tail, quoted into its
  error on a non-zero exit, is redacted at the same
  boundary.
- **JSON error envelopes are scanned by value (P4-06b).**
  A line that is a JSON error envelope (`is_error: true`,
  or an `error` key with no verdict fields) is matched
  against its decoded string values, so a CLI's own failure
  text is no longer rejected for sitting inside JSON quotes.
  Keys are never scanned, and a verdict object — whose free
  text quotes the diff under review — is never
  value-scanned.
- **Quotation lead-ins do not classify (P4-06c).** A line
  whose first non-space character is `+`, `>` or `|` (diff /
  markdown quoting), and a lead-in containing a code call
  (`print(...)`), are content under review, not the CLI
  speaking. `-` is deliberately allowed (an ordinary vendor
  bullet). Accepted residual, documented in seatstate.py:
  the bare unquoted third-party state report ("MCP server
  docs not logged in; continuing") still matches — the
  `; continuing` lookahead that would catch it encodes one
  vendor's phrasing and was rejected on that basis.
- **Suite portability.** `test_score_confirmation_v3` now
  skips cleanly when the swarm environment's `llm_chain`
  module is unavailable (it drives bench scripts that import
  it from outside the repo), matching the guard its two
  sibling modules already carry — a clean checkout reports
  the suite green instead of one import error.

### 0.13.0.dev0 (external Phase 5 test fixes)

Fixes from the external tester's Phase 5 report (2026-11-06 —
interfaces and protocol conformance), each independently
verified against master before landing. Two items needed no
fix: the missing/wrong-`jsonrpc` half of P5-05 was already
closed by P3-10, and P5-09's help exit codes by D-004/D-005
(now pinned for every subcommand):

- **SARIF conformance (P5-01).** `artifactLocation.uri` is
  now a percent-encoded relative URI reference: drive
  letters, leading slashes and `.`/`..` segments are dropped
  rather than resolved, and each remaining segment is
  percent-encoded. `startLine` is clamped to a positive
  int32, and control characters are stripped from
  `message.text`. Fingerprints and same-input determinism
  are unchanged.
- **PR posting boundary (P5-02, P5-03, P5-04, P5-11).**
  `pr --post` without `GITHUB_TOKEN` fails fast with exit 2
  before any provider call. A comment or status POST failure
  no longer discards the completed review: the failure and
  what was already posted are recorded on the report
  (`posting`), the local report is written, and the exit
  code still reflects the posting failure. Rendered PR
  comments neutralise untrusted model/diff-derived text
  (@mentions, markdown images and links, raw HTML render
  inert; the comment's own structure is untouched). The
  inconclusive gate keeps its documented `pending` commit
  status, and the status description now says the gate was
  inconclusive, explicitly.
- **MCP envelope validation (P5-05).** A request id that is
  a bool, float, null, object or array is an invalid request
  (-32600, answered with a null id); string and integer ids
  behave as before, and an absent id keeps notification
  semantics.
- **Wizard interrupts (P5-06, P5-13).** Ctrl-C in
  `codereview setup` prints "cancelled — nothing saved." and
  exits 130 — no traceback, no config written. The EOF path
  prints its abort message once, not twice.
- **Unwritable `--out` refused up front (P5-07).** Every
  command that accepts `--out` (main gate, `pr`, `loop`,
  `workflow`, `intake`, `bench`) validates the target at
  argument time and exits 2 before any provider call, where
  it previously ran the full review and then lost the
  result to a raw traceback.
- **Claim lint (P5-08).** The claim lint is now
  paragraph-level over all shipped reader docs (registered
  run records excluded by name as immutable), with a pattern
  table covering decimal, percentage and phrasing variants
  of the headline figures. All 11 of the tester's
  unqualified mutation variants now fail it; existing docs
  were qualified in place, never the lint weakened.
- **Docs and wording (P5-10, P5-12, P5-14).** Hook
  positional arguments are documented where hooks are
  documented (a bare script path receives none; a shell
  string forwards `"$1" "$2"`), the MCP server's
  single-threaded cancellation limit is documented, and the
  herdr plugin launcher says "is not a directory" for a
  path that exists but is a file.

### 0.13.0.dev0 (external Phase 4 test fixes)

Fixes from the external tester's Phase 4 report (2026-11-06 —
provider failure totality), each independently verified
against master before landing:

- **Provider transport — quota, deadlines, garbage (P4-01,
  P4-02, P4-03, P4-04, P4-05).** API error responses now read
  their bodies (bounded excerpt), so a 429 whose body names a
  quota classifies `quota` on the first attempt instead of
  burning three rate-limit retries; `Retry-After` (seconds or
  HTTP-date) floors the retry delay, capped at 120s. Every
  API call carries an overall deadline driven by the
  operator's `--timeout` (a trickling response can no longer
  pin a seat forever) and a 16 MiB streamed response cap.
  Transport-level garbage — malformed JSON, an HTML 200,
  non-UTF-8 bytes, a truncated body — surfaces as a transient
  `ProviderError` and is retried, never again mistaken for a
  model-output parse failure. Empty-content responses carry
  `kind="empty"` end to end, so the review retry layer and
  the benchmark's generation seats treat them as the content
  class they are (re-draw) instead of `unknown`/exhausted.
- **Seat-state anchoring (P4-06).** Vendor failure patterns
  now count only on lines where the CLI speaks in its own
  unquoted voice: a benign warning quoting a component's
  state (`warning: MCP server 'docs' not logged in;
  continuing`) no longer early-terminates a healthy seat as
  `blocked:auth`, and a crashed run whose stdout quotes
  failure text from a reviewed diff no longer classifies
  `blocked:auth`. The verbatim vendor lines — including
  timestamped logger-prefixed captures — still classify, and
  Claude's failure-as-result stdout channel is preserved.
- **Herdr watch backoff (P4-07).** Consecutive pane-get
  failures in the hosted watch back off exponentially
  (0.05s → 2s cap, reset on success) instead of spawning
  herdr ~13 times a second; a bounded streak of 20 with
  reconciliation still proving the session healthy ends the
  seat with the recorded herdr-unreachable outcome.
- **Benchmark durability (P4-08, P4-09).** A torn final JSONL
  line in the generation driver's records is skipped on
  resume (corruption anywhere else still raises). Seat
  metering is journaled at call time
  (`events-attempt-N.jsonl`) and merged into the record fold
  on resume, so a kill between the cache write and the fold
  no longer understates a case's attempts and tokens.
- **Future-dated waivers (P4-10).** A waiver dated more than
  one day in the future is now a `waivers.max_age_days`
  violation — it previously passed the age check trivially
  (negative age) and waived findings forever. One day of
  tolerance absorbs timezone skew from date-only parsing.
- **Single-family panel label (P4-11).** A PASS from a
  multi-seat panel whose serving seats all share one known
  model family now carries "single-family panel — no
  independent review" in its gate reasons, mirroring the
  solo-panel label. No verdict change.

### 0.13.0.dev0 (external Phase 3 test fixes)

Fixes from the external tester's Phase 3 (security) report
(2026-11-06), each independently verified against master
before landing:

- **P3-01 — policy provenance is observable (observability
  only).** The run record's policy section carries an
  `origin` (`discovered-in-repo` / `explicit` / `none`),
  the CLI warns on stderr when a repo-discovered policy is
  applied, and a change that itself adds or modifies
  `.codereview.toml` / `AGENTS.md` is flagged in the
  record's `policy_self_modification` list (from patch
  sections, plus a git-status check for the untracked-
  policy case in working-tree mode). Which policy keys
  apply, and whether hooks run, are UNCHANGED — restricting
  a discovered policy's authority awaits an owner decision.
- **P3-01 — the trust restriction has landed (owner ruling
  2026-11-06, option 1: restrict).** A policy DISCOVERED in
  the reviewed repository now keeps only its strengthening
  keys. Its `[hooks]` (commands and timeout), a
  weaker-than-`strict` `[gate]` profile, `[[paths]]
  enforce = "advisory"`, the `[waivers]` leniency values,
  `[diversity] enforce = "degrade"` /
  `exclude_builder_family`, and `[risk]` tiering with its
  seat selection are dropped back to defaults at load —
  before the hook runner is built or the gate reads the
  policy — enumerated in one audit point
  (`policy.DISCOVERED_POLICY_RESTRICTED_KEYS`, enforced by
  `policy.apply_discovered_restrictions`). Dropped keys are
  named in the record's `policy.ignored_keys`, counted in
  the CLI's discovered-policy warning (which now names the
  remedy), and returned to MCP clients as
  `policy_ignored_keys`. New `--trust-repo-policy` flag
  (CLI, and `run_gate`'s `trust_repo_policy` argument)
  honours a discovered policy in full; an operator-named
  `--policy` is honoured in full exactly as before.
  THREAT-MODEL gains the "policy may come from the reviewed
  tree" trust-boundary entry.
- **P3-02 — the deterministic scanner is no longer cubic.**
  Every unbounded gap in the `sql-string-build` rule is
  bounded to 200 chars and a single added line is scanned
  to at most 16,384 chars; the tester's 18 KB pathological
  line went from ~31 s to ~0.1 s, with legitimate SQL
  string-build findings unchanged.
- **P3-03 — redaction covers the token formats it meets.**
  PEM blocks (whole block), AWS AKIA/ASIA ids, GitHub
  ghp_/github_pat_, OpenAI/Anthropic sk- shapes, Stripe
  live/test keys, Slack xox tokens, Google API keys, JWTs,
  URL credentials, `Authorization: Basic`, and keyword
  assignments in unquoted, quoted-key, JSON and
  string-literal-value forms (value floor lowered to 4).
  The scanner flags the same provider prefixes. Redaction
  remains pattern-based best-effort (the README now says
  so); generically encoded forms (base64 / hex /
  URL-encoded / line-wrapped copies of a key) are a
  documented residual.
- **P3-04 — the gate process makes itself non-dumpable on
  Linux** (prctl PR_SET_DUMPABLE), at CLI start, at MCP
  server start, and lazily in the evidence executor and
  the discovery probe — an env-only sandbox child can no
  longer read the gate's environment out of
  /proc/<pid>/environ.
- **P3-05 — a deeply nested MCP frame no longer kills the
  server**: RecursionError at parse time is answered
  -32700, recorded in the errors ledger, and serving
  continues.
- **P3-06 — sandbox runs kill their process group on the
  normal exit path too**, not only on timeout: a
  backgrounded child with redirected stdio no longer
  survives a passed evidence run. (The notifier runner was
  checked and left alone: it does not start a session, so
  no group exists to kill.)
- **P3-07 — the discovery `--version` probe is capped**
  (64 KB retained per stream, child killed past the cap)
  and honours its never-raises contract end to end.
- **P3-08 — herdr detection fails closed on malformed CLI
  output**: null, non-object and deeply nested JSON all go
  inert with the reason recorded, never an exception.
- **P3-09 — a named repo must exist.** An explicitly empty
  or nonexistent/non-directory `--repo` is a clear exit-2
  error in both patch and git modes (patch mode previously
  accepted it and silently skipped policy, AGENTS.md and
  evidence context); the MCP run_gate applies the same
  validation.
- **P3-10 — the MCP transport enforces the protocol it
  speaks**: frames whose `jsonrpc` field is absent or not
  "2.0" get -32600 (notifications keep their no-response
  semantics), non-finite ids are answered as null, and
  responses are serialised with allow_nan=False.
- **P3-11 — one shared containment helper**: `_is_within`
  lives in core and is used by the CLI loaders, the
  file-context collector and the AGENTS.md collector
  (previously two sites called commonpath directly, one
  without the fail-closed ValueError handling).
- **P3-12 — notifier summaries are sanitised at the single
  chokepoint** argv and the record share: control/escape
  bytes are stripped (ANSI/OSC sequences lose their bytes)
  and the summary is capped at 500 chars with an ellipsis
  marker.

Follow-up completions from the tester's response to the
Phase 2/3 follow-ups (2026-11-06), each independently
re-verified against master before landing:

- **P3-02 follow-up — the 16K scan cap is removed.** The
  prefix cap above blinded every rule past 16,384 chars
  (a fake AWS key planted at offset 20,000 of one line
  produced zero findings). The bounded regex gaps did
  the DoS work — a ~1 MB pathological line scans in ~3 s,
  near-linear — so lines are now scanned IN FULL up to a
  1,000,000-char hard bound. Past the bound the prefix is
  scanned and a minor `scan-line-truncated` finding
  records that the tail was not checked: a line that long
  never silently passes. (The residual that stands: SQL
  keywords and their concatenation markers more than 200
  chars apart are not one statement construction for the
  `sql-string-build` rule.)
- **P3-04 follow-up — the sibling-process residual is
  documented and surfaced, not closed.** `PR_SET_DUMPABLE`
  protects only the gate process; in env-only mode a
  sandboxed child can still read any dumpable same-uid
  sibling process's environment via `/proc/<pid>/environ`
  (shell, IDE, other agents). THREAT-MODEL gains residual
  7 (the "provider keys never reach an evidence process"
  property depends on namespace mode; env-only is not
  suitable for untrusted trees), the README sandbox
  paragraph carries the same qualification, and a run
  that executes env-only while the gate environment
  carries key-shaped variable names warns once on stderr
  and records the exposure in the evidence record's
  sandbox section (variable names only, never values).
- **P3-01 follow-up — MCP verdicts carry policy
  visibility.** `run_gate` captures the CLI's stderr and
  discards it on success, so the discovered-policy
  warning never reached MCP clients. The verdict payload
  (both `run_gate` and `get_verdict`) now carries
  `policy_origin` and `policy_self_modification` from the
  record — always present (null / [] when the run had no
  policy section), so clients can rely on the shape.

### 0.13.0.dev0 (external Phase 2 test fixes)

Fixes from the external tester's Phase 2 report (2026-11-06),
each independently verified against master before landing:

- **P2-01 — strict + incomplete no longer downgrades a
  blocker.** The `_gate` incomplete-coverage branch returned
  "inconclusive" under strict mode even with a blocking
  finding present; it now carries the same `not blocking`
  guard as the degraded branch.
- **P2-02 — merge_findings is order-invariant.** The greedy
  merge compared each finding only against each group's
  founding title, so grouping (and, under `balanced`, the
  verdict) depended on input order. Inputs are first sorted
  by a canonical content key (file, category, line, title,
  severity, sources — never the assignment-order id).
- **P2-03 — diversity family tags are normalised.**
  `known_families` / `assess_panel` compare strip+casefold
  forms, so "OpenAI" vs "openai" no longer counts as two
  families and builder exclusion no longer fails silently
  on case. Tags stored elsewhere are untouched.
- **P2-04 — policy loader robustness.** A UTF-8 BOM no
  longer makes a valid policy unloadable (decoded as
  utf-8-sig), and a deeply nested document now raises
  PolicyError naming the excessive nesting depth instead of
  leaking RecursionError.
- **P2-05 — risk path patterns component-anchored.** The
  migrations, secrets and deserialization patterns no
  longer match keywords buried inside longer components
  ("im**migration**", "no**secrets**.py"); canonical paths
  (db/migrations/…, config/secrets.yaml, .env,
  lib/deserialize.py) score exactly as before.
- **P2-06 — claimed outcomes read counts and negation.**
  "12 passed, 0 failed" and "did not fail" are pass claims
  (previously read as FAILED); "0 errors" is a pass claim
  (previously no claim). Counts are read first, then a
  negation guard, then the original word search.
- **P2-07 — claim parsing is linear and single-pass.** The
  labelled-line trailing-outcome regex backtracked
  quadratically on long separator runs (~12s at 12KB; now
  milliseconds), and `verify_report_claims` no longer
  parses the report text twice.
- **Survivor pins.** Regression tests now hold behaviours
  the Phase 2 mutation pass verified: the balanced
  unattributed-source guard, deterministic source-lens
  stamping, tiering missing-seat dedup, and lens-pin edges
  (ghost seat / unknown lens ignored, single-seat fallback,
  dual pins).

**P2-08 — NOT landed (blocked, decision pending).** The
verified finding stands: under `balanced`, an unbound panel
gets positional lens assignment and the same finding can
flip PASS/BLOCKED by binding state. The prescribed
fail-closed fix (run_review raises without a seat_lenses
binding) cannot land as specified: the CLI and policy
surfaces have NO way to supply a binding (zero seat_lenses
references in cli.py / policy.py / userconfig.py — bindings
are produced only by bench's derive_seat_lenses and direct
library callers), so the raise would make the shipped
`--gate-profile balanced` flag and a policy-file
`[gate] profile = "balanced"` fail on every run with no
possible remedy. Landing it needs a product decision:
add a CLI/policy binding surface in the same change, or
have the CLI derive and record an explicit binding.

### 0.13.0.dev0 (external Phase 0–1 test fixes)

Version bumped to 0.13.0.dev0 (pyproject.toml and
core.VERSION, kept identical) for the fixes from the
external tester's Phase 0–1 report (2026-11-06):

- **D-001 — deterministic records.** run_review's job
  executor folded reviewer results in completion order, so
  reviewer_reports order, merged findings' sources order and
  the markdown render varied run to run for identical inputs.
  Results are now collected and folded in submission order
  (the run_verification pattern); gate semantics unchanged.
- **D-003 — self-testing sdist.** MANIFEST.in now ships the
  full tests tree (fixtures included), probes/, bench/corpus/,
  examples/ and the top-level CHANGELOG.md, precedents.json,
  fixtures-manifest.json and THREAT-MODEL.md, so an unpacked
  sdist can run its own suite. bench/ beyond the corpus —
  registered run material — stays out.
- **D-004 — `--version`.** The CLI answers `--version` with
  the package version and exit 0 (both entry points are the
  same main()).
- **D-005 — subcommand `--help`.** `policy --help`,
  `bench --help` and `mcp --help` exited 2 with a bare usage
  line; all fifteen subcommands' `--help` now prints real
  help and exits 0.
- **D-007 — environment-dependent tests skip cleanly.** The
  three test files needing the swarm's llm_chain module skip
  with a stated reason when it is not importable, instead of
  erroring at import.
- **Flake fix.** The notify/risk "never changes the outcome"
  comparisons now also exclude the report's top-level
  duration_ms, which intermittently failed them on timing
  alone.

### verdict record schema v1.0.0

The run record is now a formal, versioned contract
(`src/codereview/record_schema.py`): `RECORD_SCHEMA` +
a stdlib-only validator, with every record validated by
the core at emission and re-validated by `write_report`
before it reaches disk — so the CLI, MCP, GitHub, and loop
surfaces all emit the same v1 record. Added sections:
`schema_version` ("1.0.0", alongside the unchanged
`codereview.report/1` tag), uppercase `verdict` beside the
legacy lowercase `gate`, `scope`, `checks` (run / not_run /
unavailable — checks that did not run are visible),
`panel` (seats, families, degraded state), `cost`
(explicitly `not_available`: the core has no cost data and
invents none), `duration_ms`, `waivers`, `provenance`,
`record_identity` (content-hash id; writer-stamped file
name), and `verdict_semantics` (a PASS means no actionable
issue found under the checks that ran — not a correctness
guarantee). Emission fixes, no verdict-logic changes:
verify-mode records now carry `degraded_causes` and
`patch_chars` (both previously absent there). Documented
gaps, stated in the schema and README: verify mode lists
coverage/evidence/policy as `checks.not_run`; the loop
summary is a container, not a v1 verdict record; legacy
records without `schema_version` are pre-v1, not corrupt.
Golden PASS / BLOCKED / INCONCLUSIVE fixtures and parity,
tamper, and self-tests in `tests/test_record_schema.py`.

### Epic E2 + E4 (tiered panels + escalation)

E1's risk band now sizes the panel that reviews a change,
and the smaller tiers carry a safety valve: escalation to
the full panel within the same run. Both are driven by the
[risk] table of .codereview.toml (`tiering = true`, which
requires `enabled = true` — policy load rejects the
combination otherwise, in the B1 style) and recorded in
the run record's new `tiering` section
(`codereview.tiering/1`). Unconfigured, a run is
byte-identical to before this epic.

- **Tiering (E2).** Band "low" runs a designated
  pre-screen seat (or seats) only (`prescreen_seats`;
  default: the composed panel's first seat); "medium"
  runs a reduced panel (`medium_seats`; default: the
  first tasked seat per lens); "high" runs the full
  panel and requires evidence — a supplied evidence
  record is judged by the Epic C rule exactly as today,
  and a missing one blocks the gate under C3's
  missing-required-evidence consequence. Under an
  explicit seat->lens binding the tier is a subset of the
  bound tasks — a seat serves exactly its bound lens(es),
  never a re-mapping (S1); under the legacy assignment
  the tier's seats form a smaller panel tasked by the
  ordinary derivation rule. A configured seat that is not
  on the panel is recorded as missing, never silently
  dropped; if a tier would be left with no serving seat,
  the run falls back to the full panel with the reason
  recorded.
- **Escalation (E4).** The reduced tiers execute as
  stage 1; if stage 1 returns a blocking finding (the
  gate's own blocking severity set), a reviewer failure,
  or leaves a lens the full panel tasks unserved, the
  rest of the panel executes as stage 2 in the same run
  and the verdict is computed on the full evidence by the
  normal rules. Escalation never removes a stage-1
  report or finding. Every trigger that fired is
  recorded in the `tiering` section and summarised in
  the gate reasons.
- **Cost.** On the public bench split (27 cases, a
  synthetic all-pass 4-seat panel, default thresholds:
  26 cases band low, 1 medium, 0 high) tiering spends 54
  seat calls against the untiered panel's 108 — a 50%
  drop. High-band recall is unchanged by construction:
  the high tier's stage is the identical full task list
  and prompts as an untiered run (fixture-pinned), plus
  the evidence requirement.
### 2026-11-05 (registration verifier: Addendum A append)

Addendum A to the 2026-11-05 pre-registration was appended to the
registration's §3 on 2026-11-05 (signed the same day by the owner
and one independent reviewer; its item-2 disclosure completed and
its item-4 wording aligned to the merged empty-content
classification; addendum body hash
`d83c93977d66769c614f6510159c0713f3b2addf8ba3c7854a7d6b5bdeea528d`,
recorded in §3). The append changed the registration's body hash,
so `bench/scripts/verify_registration.py` now treats the
Baseline-v2-§6 post-fill body state the way it already treated the
A5 set hash:

- The post-fill body hash (`9e38217e...`) is reported SUPERSEDED,
  and only when the body recomputes to the new state; the
  post-append body hash (`5d9bea16...`) is the current
  expectation, verified by strict equality. No check was removed
  or weakened: exit 0 still requires the registration body to hash
  to exactly the one authorised current value, and any other body
  state — including the superseded one — fails. Attempts consumed
  under the registration remain 0; no run was started.

### Epic C5 (sandbox safety audit)

Ticket C5's machinery largely shipped with the Epic C runner;
this track audited it line by line against the ticket ("no
network by default, resource limits, run in temp worktree;
never run untrusted PR code with secrets" — acceptance:
documented threat model + tests) and closed the one real gap.

- **Gap closed — captured output is now capped.** The
  executor buffered a child's full stdout+stderr in the gate
  process's memory (`communicate()`), so a spewing command
  could grow it without bound until the timeout fired. Each
  stream is now drained by a reader thread under an 8 MiB
  per-stream cap: past the cap the parent keeps draining and
  discarding (the child never blocks on a full pipe and its
  exit status is unaffected), the record's hash and tail
  cover the capped bytes, and a truncation marker in the
  output says when the cap bit; and if a detached process
  holds a pipe open past the post-kill settle, the capture is
  marked incomplete rather than silently partial (gate
  round-1 majors, accepted in substance). The record's
  `sandbox.limits` block states the cap. The wait lives in a named supervised
  wait (`_supervise_sandbox_run`) — deadline-bounded waits,
  bounded joins, process-group kill on expiry — and the v14
  subprocess-timeout guard accepts it by name, following the
  Epic K2 seat-wait precedent.
- **Already met, now pinned** (`tests/test_sandbox_c5.py`):
  the CPU and per-file rlimits actually reach the child;
  provider-key-shaped variables, tokens, and the SSH agent
  socket never cross the allow-list, and `allow_network`
  re-admits proxy variables only; the throwaway copy is
  deleted on every exit path (normal, timeout kill, copy
  failure, claim verification); namespace mode is a real,
  different network namespace in which a connect attempt
  fails (where `unshare` works).
- **Documented, not faked:** `THREAT-MODEL.md` at the
  repository root is the written threat model — controls,
  trust boundaries, and residual risks stated plainly. The
  headline residuals: no filesystem isolation (absolute-path
  reads/writes escape the copy — run the CLI in a VM or
  container for genuinely hostile trees), and **no memory
  cap**: an address-space rlimit would break legitimate
  toolchains (Node/V8 and JVM address-space reservations;
  `npm` is a built-in adapter), so memory growth is bounded
  only by the wall-clock/CPU limits and the risk is
  documented rather than theatre-capped.
### Epic E1 (risk scorer)

A review run can now record a deterministic risk score for
the change under review. When the project policy's new
`[risk]` table sets `enabled = true`, the run record gains a
`risk` section: the score (0–100), its band (`low` /
`medium` / `high`), a human-readable reason for every point,
and the per-signal breakdown (files and lines changed,
pattern classes touched, dependency files).

- **Deterministic by contract:** `codereview.risk` is a pure
  function of the kept diff sections and the resolved
  thresholds — no model calls, no randomness, no clock. The
  same diff under the same policy scores identically on
  every run (test-pinned, including section order).
- **Signals:** touched sensitive patterns — auth, payments,
  crypto, migrations, secrets, deserialization — matched on
  changed paths and added lines, each class contributing its
  points once with the pattern subtotal capped at 60;
  dependency-manifest changes (+15: package/requirements/
  cargo/go/composer/gem manifests and lockfiles, `*.txt`
  under a `requirements/` directory included); change size
  in fixed tiers up to +25.
- **Descriptive only:** in E1 the score never changes a
  verdict, a finding, or any gate input (test-compared with
  risk on vs off). Tiering (E2) and escalation (E4) consume
  the section next.
- **Schema:** `[risk]` (`enabled`, `medium_threshold`,
  `high_threshold`) is validated by the policy loader with
  line-referenced errors like every other table — non-bool
  `enabled`, thresholds outside 0–100, and an inverted
  medium/high pair are loud errors. `codereview policy
  check` renders the table when — and only when — scoring
  is enabled.
- **Equivalence:** with `[risk]` absent or disabled, a run
  is unchanged in every particular — no `risk` key in the
  record; the registered bench sets are untouched.
- **Verification:** 38 new tests (`tests/test_risk.py`),
  37 failing on pre-E1 master (the module does not exist
  there; the one pass is an unknown-table coincidence in a
  negative-validation test) — scorer fixtures per pattern
  class, size tiers, the pattern cap, determinism, policy
  schema errors, and record integration through
  `run_review` with stub seats.

### Epic E3 (panel-diversity enforcement)

A project can now enforce panel diversity in the
`[diversity]` table of its `.codereview.toml`, judged on the
COMPOSED panel before any seat is called:

- **Minimum families:** `min_families = N` requires the panel
  to span at least N distinct known vendor families (seat
  metadata — registry tags or `--seat-meta`; `unknown` never
  counts). This is distinct from `[panel] min_families`,
  which judges the seats that actually served, after the
  round. A violation labels the run degraded with the cause
  `panel diversity below minimum` and is recorded in the
  record's `diversity` section and as an applied
  `diversity.min_families` rule in the policy section.
- **Enforcement mode:** `enforce = "degrade"` (the default)
  records the violation as advisory — never gate-changing.
  `enforce = "block"` additionally makes it a blocking
  policy violation, exactly like any other.
- **Builder exclusion:** with `exclude_builder_family =
  true`, when the run's caller knows the builder's vendor
  family (the `builder_family` argument — no CLI run path
  knows it today, so there the exclusion simply never
  engages; no builder identity is ever invented), seats of
  that family are excluded from the panel when the remaining
  panel still meets the minimum — otherwise they stay, and
  the record says why. An excluded seat's lens is never
  reassigned by the check: the seat->lens binding machinery
  treats it as an absent seat.
- **Equivalence:** with no `[diversity]` configuration, a
  run is unchanged in every particular — no `diversity` key
  in the record, no applied rule, identical verdicts; the
  registered bench sets are untouched.
- **Verification:** 27 new tests (`tests/test_diversity.py`)
  — panel assessment (minimum met/breached, unknown-family
  handling, builder exclusion possible/refused/emptying/
  unknown/absent), policy schema + rendering, and run_review
  integration (degrade vs block, exclusion never calling the
  builder's seats, unconfigured equivalence).

### Epic C4 (builder-claim verification in the run record)

Builder-claim verification now lands in the run record. The
machinery is not new — `evidence.parse_claims` /
`evidence.verify_claims` (Epic C) already parsed a builder
work report's claimed commands and re-ran them in the sandbox
behind the standalone `codereview evidence --claims` surface.
What is new is the record-facing contract around them
(`src/codereview/claims.py`, composing the evidence runner —
no second parser, no second executor):

- **Recorded in the run record:** on a verification run
  (`--verify-previous` with `--builder-response`), the record
  now carries a `claim_verification` section: per-claim
  entries with the claimed outcome, the re-run's actual exit
  code, duration, and output sha256, plus a summary. A run
  with no builder report carries no section.
- **Statuses:** `verified` (the re-run matches the claim),
  `mismatch` (the re-run contradicts it — the claim is
  downgraded, recorded as not standing with claimed vs
  actual outcomes stated), `unverifiable` (the re-run could
  not be performed), and `unparsed` (a line shaped like a
  claim — a backticked command or a claim label — that does
  not parse to an unambiguous command + outcome: recorded,
  never guessed at, never executed). Ordinary prose is not a
  claim attempt and is not recorded.
- **Evidence, never a gate input:** claim verification is
  recorded evidence only. No claim status changes the
  verdict, a finding, or any other gate input, and nothing
  in the gate reads the section — a mismatch downgrades the
  claim, never the gate (test-compared: identical panel,
  honest vs downgraded claims, identical gate). The section
  states this boundary in its own `boundary` field.
- **Never raises:** malformed reports, non-text input, a
  missing tree, and sandbox failures are recorded outcomes
  (`unverifiable`, with the reason), never exceptions; the
  run's record is produced regardless.
- **Verification:** 20 new tests (`tests/test_claims.py`) —
  18 fail on pre-C4 master with an empty-module shim (the
  module does not exist there at all); the 2 passes pin
  pre-existing behaviour by design (no builder report ⇒ no
  section; a review run ⇒ no section).

### Epic L3 (lifecycle hooks)

A project can now declare shell commands in the `[hooks]`
table of its `.codereview.toml` that fire around a review
run: `pre_run` before any seat call, `on_blocked` when the
run's first seat ended in a K2 blocked class (quota / auth /
input / stalled), and `post_verdict` on every run — the two
post-record events after the record is written, so they are
handed its path (as `$CODEREVIEW_HOOK_RECORD`, and as `$2`;
the event name is `$CODEREVIEW_HOOK_EVENT` / `$1`).

- **One-way enforcement:** hooks are notification, never a
  gate input. Each hook's outcome — status, exit code,
  duration, output sha256 + redacted tail — is captured into
  the record's `hooks` section; a hook that fails, times
  out, or names a missing command is recorded and the run
  continues, its verdict exactly what it would have been
  without the hook (test-compared).
- **Sandboxed, C5 verbatim:** hooks execute through the
  Epic C evidence runner (`codereview.hooks` builds a
  single-command evidence config — no second executor):
  throwaway copy of the tree as cwd, allow-listed
  environment (no provider keys), no network by default,
  per-hook timeout (the `[hooks] timeout` key, defaulting
  to the evidence bound) with process-group kill.
- **Schema:** `[hooks]` is validated by the policy loader
  with line-referenced errors like every other table
  (unknown keys, empty/non-string commands, non-positive
  timeouts are loud errors). `codereview policy check`
  renders the table when — and only when — a hook is
  configured.
- **Equivalence:** with no `[hooks]` commands, a run is
  unchanged in every particular — no `hooks` key in the
  record, identical prompts and verdicts; the registered
  bench sets are untouched.
- **Verification:** 25 new tests (`tests/test_hooks.py`),
  none passing on pre-L3 master — schema errors, sandbox
  delivery (event/record/env), the C5 environment marker,
  exactly-once + ordering through the real CLI with stub
  seats, the fallback-primary trigger, and verdict identity
  across absent vs failing hooks.

### Epic L2 (MCP server for the gate)

The gate is now callable from inside another agent's loop:
`codereview mcp serve` speaks the Model Context Protocol
over stdio and exposes two tools — `run_gate` (a patch, or a
git range in a repo, plus an optional policy path → the
verdict and the run record's path) and `get_verdict` (a
stored record → verdict summary and findings).

- **In-tree protocol subset, stdlib only:** the wire layer
  (`codereview.mcp_transport` — newline-delimited JSON-RPC
  2.0 framing, dispatch, error ledger) and the tool layer
  (`codereview.mcp_tools` — handshake negotiation for
  protocol versions 2025-03-26 / 2024-11-05, tools/list,
  tools/call) are separate modules; no new dependency.
- **Serving only:** the server is a front door onto the
  existing gate, not a new gate — a run goes through the
  CLI's own `main()` with the arguments translated, so the
  served verdict is the CLI's verdict on the same change and
  the record on disk is the ordinary run record. The review
  path consumes no MCP tools; reviewers stay read-only and
  tool-less (Epic F2 unchanged).
- **No credentials, no built-in panel:** the server stores
  nothing; seats resolve from the operator's saved setup (or
  $CODEREVIEW_PROVIDERS) under the CLI's own discipline.
  With no setup, run_gate answers with the CLI's not-set-up
  message verbatim.
- **Fail-closed wire:** malformed JSON, non-object frames,
  oversized frames (16 MiB cap, discarded in sync), and
  handler crashes are each answered or recorded in the
  server's error ledger and logged to stderr — the loop
  never dies on a bad frame. Tool arguments are validated
  against the published schemas (unknown keys, wrong types,
  patch+range together are refused before anything runs).
- **Verification:** 15 new tests (`tests/test_mcp.py`), none
  passing on pre-L2 master — transport failure modes,
  handshake/list, MCP-vs-CLI verdict equality in-process,
  the no-setup answer, and a full subprocess session (a
  minimal in-tree client over a real stdio pipe, seats from
  a local OpenAI-compatible stub) whose verdict is compared
  against the CLI binary's on the same diff. A brand-name
  MCP client session (Claude Code / Codex) is UNVERIFIED:
  no agent CLI on the build machine is logged in. Full
  suite 1005/1005 on the branch; 1018/1018 on master after
  the parallel L5 merge.
### Epic L4 (attention notifications)

A gate run can now call the operator back: when a seat
enters a blocked state (the Epic K2 classes) or the gate
reaches a verdict, the run executes one local command the
operator configured — a terminal bell, a desktop toast, a
herdr-style attention hook. No hosted service, no
CodeReview-managed endpoint.

- **User setup only:** the command lives in a `[notify]`
  table in the saved user config (`command = [...]`, an
  argv list) — notifications are operator preference, not
  project contract, so the project policy
  (.codereview.toml) has no notify key and refuses the
  table as unknown. The wizard's saved-file writer carries
  the table only when set; an unchanged setup stays
  byte-identical.
- **Argv contract:** the command runs directly (no shell)
  with two arguments appended — the event name and a
  one-line summary (`seat cx blocked:quota`,
  `gate blocked: 3 finding(s)`). Duplicate suppression is
  per run: once per (seat, blocked class), once for the
  verdict.
- **Bounded and recorded:** each invocation is capped at
  5 s; its outcome (ok / failed / timeout / error, exit
  code, duration) lands in the record's `notifications`
  section. A failing or hanging notifier never delays the
  run beyond the bound and never changes a finding or the
  verdict — test-compared against the unconfigured run.
  Unconfigured means zero trace: no invocations, no record
  section, prompts byte-identical.
- **Distinct from Epic L3 hooks:** L3 is project-level
  automation in the policy file, executed in the evidence
  sandbox; L4 is the operator's personal command from the
  user setup, executed as the operator. The two share no
  machinery.
- **Verification:** 28 new tests (`tests/test_notify.py`);
  23 fail on pre-L4 master, the 5 passes being the
  by-design pins (policy rejection, byte-identical saved
  file, and the unset-means-silent equivalences). Coverage:
  the Notifier unit contract, the real subprocess runner
  (including a hanging command bounded by the timeout),
  the user-config table (round-trip, byte-identical
  default, loud ValueError when malformed), run_review and
  run_verification integration (exactly-once events,
  outcome-invariance, prompt identity), and the CLI seam
  end to end (setup → run → record on disk).

### Epic L5 (first-class local-model seats)

Local model servers are now first-class seats: named
presets in the provider registry for the endpoints a user
runs on their own machine, offered by the setup wizard with
a short recipe, replacing the unnamed `openai-compatible:`
escape hatch for the local case (the hatch itself is
unchanged).

- **Registry** (`codereview.registry`): `ollama`
  (http://localhost:11434/v1) and `lmstudio`
  (http://localhost:1234/v1) presets with family tag
  `local`, plus the generic form
  `local:<name>:<base-url>|<model>` for any other
  OpenAI-compatible local endpoint. A preset names an
  endpoint, never a panel — the serving model is still the
  user's pick (`ollama:<model>`), per the first-run rule.
- **Keyless by construction:** local presets carry
  `key_env` None — no credential is read, no Authorization
  header is sent, and the wizard never prompts for a key
  for a local seat (there is none). Account rotation does
  not invent `KEY_ENV_2`-style names for them; the account
  label in records is `local:<seat>`.
- **Wizard:** local presets are listed as their own
  section — endpoint, suggested model, and the recipe
  (start the server → pick the preset → `codereview
  doctor` probe) — and the per-seat summary states the
  no-network nature ("runs on your machine; the review
  never leaves it"). Hosted seats' key-env summary is
  unchanged.
- **Ordinary seats:** a local seat is built, pooled, probed
  by `doctor`, and recorded like any other, with family
  `local` travelling on the callable into the record's
  seat metadata — so the independence checks see it
  honestly (never a second vendor family). Non-local specs
  and records are untouched. 13 new tests
  (`tests/test_local_seats.py`), 11 failing on pre-L5
  master (the escape-hatch regression and the
  malformed-spec test pass on both by design); full suite
  1003/1003.

### Epic L1 (AGENTS.md ingestion)

Reviewer context now includes the repository's own guidance:
`AGENTS.md` at the repo root and nested along the changed
paths is ingested at run start, alongside (never instead of)
`.codereview.toml`.

- **Ingestion** (`codereview.agentsmd`, wired into repo
  reviews; `--no-agents-context` opts out): discovery is
  deterministic — the root plus the ancestor directories of
  the changed paths, ordered nearest-wins (root first; the
  file nearest a changed file governs on conflict, and the
  prompt says so). A `## Code Review Rules` section is
  surfaced at the head of the attached context as advisory
  review rules the panel may cite in findings.
- **Trust model:** the files are untrusted content on the
  diff's own terms — passed through the review path's
  redaction, delimited in the prompt as data under a header
  that forbids following instructions inside them, and
  structurally unable to change a gate rule, the panel, or
  a record field (pinned by a prompt-injection test: a
  hostile AGENTS.md demanding a pass leaves the gate, the
  findings, the panel, and the gate-profile section
  byte-identical to the no-guidance control run). The TOML
  policy remains the only machine-enforced layer.
- **Bounds + provenance:** capped per file (16,000 chars)
  and in total (32,000), truncation marked in the text and
  recorded per file; the run record's `agents_context`
  section carries each ingested file's path and the sha256
  of its raw bytes, its sizes, and whether its rules section
  was present. Nothing is silently dropped — the collector's
  ledger covers skipped files with reasons.
- **Equivalence:** with no AGENTS.md on any changed path
  (or with the opt-out), prompts and records are
  byte-identical to the pre-L1 construction; the bench and
  registered confirmation runs never pass the new argument,
  so their prompts are unchanged. 17 new tests
  (`tests/test_agents_md.py`), none passing on pre-L1
  master; full suite 990/990.

### Epic K3b (herdr ecosystem artefact)

Presence in herdr's ecosystem, with the engine staying in
the pip package: a herdr plugin artefact and an agent skill,
both shipped in this repo (and, via a new `MANIFEST.in`, in
the sdist — verified: a test sdist build carries both).

- **Herdr plugin** (`herdr-plugin-codereview/`):
  `herdr-plugin.toml` (`superstartelecom.codereview`,
  `min_herdr_version` 0.9.0 — the floor K3a verified)
  declares one workspace action, "CodeReview: review current
  workspace", and one overlay pane entrypoint. Both run the
  launcher, `codereview_launch.py` (Python, stdlib only): it
  locates `codereview` on PATH — if absent it prints the
  `pip install codereview-ai` hint and exits non-zero
  *before doing anything else*, so that failure has no side
  effects — resolves the workspace from herdr's invocation
  context (`workspace_cwd`), reads an optional
  `policy`/`out` config from the plugin config dir, runs the
  gate in the workspace streaming its output, and exits with
  the gate's own exit code. The launcher stores no
  credentials, makes no network calls, and writes nothing
  itself (imports and read-only file opens are pinned by
  AST tests); the only files a run creates are CodeReview's
  own records in the reviewed workspace.
- **Agent skill** (`skills/codereview/SKILL.md`, standard
  Agent Skills format): teaches an agent to run the gate,
  read the JSON record as the source of truth, and report
  PASS / BLOCKED / INCONCLUSIVE honestly — a BLOCKED is
  never softened, an INCONCLUSIVE is never upgraded, and no
  verdict may be claimed that the record doesn't carry.
- **Verified here:** the launcher against a stub
  `codereview` honouring the real CLI's printed contract
  (verdict/record lines, exit codes 0/1/2, config
  pass-through, no-side-effect failure); the plugin's
  action contract against a stub `herdr` invoking the
  manifest argv the way herdr does (cwd = plugin dir,
  `HERDR_PLUGIN_*` env); and an end-to-end smoke of the
  launcher driving the real CLI (two scripted agent seats)
  to a real PASS record on a scratch repo. 20 new tests,
  all failing on pre-K3b master.
- **UNVERIFIED — plugin link.** Real herdr is not installed
  on the build machine (no Rust toolchain), so
  `herdr plugin link` on a clean profile and the action's
  appearance in `herdr plugin action list` on a real herdr
  have NOT been run; the stub-herdr contract test above is
  the closest honest exercise. The marketplace listing
  remains GitHub-gated and out of scope.
- **UNVERIFIED — skill dogfood.** The only agent CLI on
  this machine (codex) is not logged in, and no other agent
  CLI is installed, so no fresh agent session has yet been
  driven through the SKILL.md; no transcript is claimed.
  The skill's procedure is the exact command sequence the
  end-to-end smoke above executed by hand.

### Epic K3a (herdr pane hosting)

Agent seats named in the saved config's `[hosting]` table
(`herdr = ["seat", ...]` in the user setup file) can now run
inside herdr panes instead of headless subprocesses, so a run
is watchable from herdr's UI. The `agent:` spec grammar is
unchanged — hosting is a config hint, never part of a spec —
and herdr is never a hard dependency.

- **Optional by construction** (new `herdrhost` module):
  detection probes, in order, `herdr` on PATH → version floor
  (`MIN_HERDR_VERSION` 0.9.0, set from the inspected 0.9.5
  tree) → feature-detect against `herdr api schema --json`
  (the used methods and the `pane.agent_status_changed` /
  `pane.exited` event names must be present) → a reachable
  session (`herdr api snapshot`). Any failure leaves the
  adapter inert: every seat runs headless exactly as before,
  and the run record carries exactly one `herdr_hosting` line
  saying why. With no hosting configured, records are
  byte-identical to pre-K3a records.
- **CLI wrappers only** — no raw socket. The seat launches
  via `herdr pane run` (herdr's primitive for ordinary
  terminal processes; `agent start` is for interactive
  prompting of recognised agents). The review packet is
  never typed: the pane command redirects stdin from the
  prompt file, and `$CODEREVIEW_PROMPT` is set via
  `workspace create --env`. Output and the exit code land in
  files, and supervision reads process truth from them —
  the same capture files, pattern table, and terminal
  classifications as the headless runner, with identical
  error messages. A hosted seat's run leaves a `hosting`
  receipt in the record (transport, herdr version, pane,
  advisory observations), next to `seat_state`.
- **Advisory pane state, failure discipline.** Herdr's
  `agent_status` is signal #4 (K2): it annotates the receipt
  and may raise an advisory `blocked:input` episode in the
  seat-state trace; it never decides an outcome, and when it
  disagrees with the files, the files win and the
  disagreement stays in the receipt. There is no `events`
  CLI in herdr, so the subscription is a supervised `pane
  get` watch; a break in it is treated as `events_lost` and
  reconciled via `session.snapshot` — same pane, same
  terminal, or the seat fails. Herdr dying mid-run, a pane
  exiting early, or a restarted session are recorded seat
  failures; a resumed session is never silently continued
  and no command is ever re-run inside an attempt.
- **Environment discipline** (spec U7): we add only
  `CODEREVIEW_PROMPT` (a path) to the pane — plus `HOME` for
  a `home=private` seat. Operator API keys are never added;
  the pane session's own environment is the user's, which is
  the point of hosting a subscription CLI.
- **UNVERIFIED — live smoke.** Real herdr is not installed
  on the build machine (and there is no Rust toolchain to
  build it), so the spec's live-smoke leg — a real herdr
  session hosting two seats through a real gate run — has
  NOT been run. The full lifecycle, hosted/headless
  equivalence, and the chaos cases (herdr dies mid-run,
  event break + reconcile, vanished pane, restarted
  session, contradictory pane state) are covered against a
  stub `herdr` executable implementing the used CLI surface
  (31 new tests; 30 fail on pre-K3a code, the one pass being
  the byte-identity guard for unchanged setups). The
  adapter's reading of herdr's response envelopes is taken
  from herdr's source and docs, not from a live session.

### Epic K2 (seat-state supervision)

Every seat in a run now carries a live state — pending →
working → done / blocked:<class> / failed / timed-out, with
blocked classes quota, auth, input, stalled — shown on the
CLI's stderr as transitions happen and persisted per seat in
the record (`seat_state`, plus `seat_state_primary` when a
fallback attempt determined the outcome), alongside the
existing error_detail machinery. A blocked seat degrades the
panel exactly as a seat failure does today (fallback with the
reason recorded, or degraded → INCONCLUSIVE); state itself
never changes a verdict.

- **Detection is ours, over subprocess signals** (new
  `seatstate` module): exit codes, captured output, activity,
  timeout. The per-CLI failure-pattern table is probe-grounded
  (the K spec's U6 matrix): Codex auth patterns are taken from
  a live logged-out capture of codex-cli 0.164.0-alpha.9, its
  quota text from the vendor's own source; Claude's quota/auth
  text from the official error reference; Gemini's quota text
  from the official FAQ. Gemini auth text is UNVERIFIED in the
  docs, so gemini ships no auth pattern; the `input` class is
  wired but pattern-less for the same reason. Patterns scan
  stderr while a seat runs and, after a non-zero exit, stderr
  then stdout (Claude prints in-run failures as its result);
  a successful run's stdout is never scanned.
- **Supervised agent wait** (`providers.command_agent`): the
  single communicate() wait is now a poll loop over the
  capture files — a verified blocked pattern followed by a
  grace period of total silence terminates a stuck seat early
  as blocked; a seat killed by its timeout while silent past
  the stall bound ends blocked:stalled, while still producing
  output it ends timed-out. Stall episodes are live/recorded
  liveness signals, never kills by themselves. All existing
  ProviderError messages are unchanged; errors now also carry
  `seat_facts` for the record.
- **Discovery offers all three CLIs** (U6-verified forms):
  Codex (`codex exec -s read-only --skip-git-repo-check -`;
  form verified live + docs, end-to-end success not live-
  verified — no login on the build VM) and Gemini CLI
  (`gemini -p "…"`; docs-verified only), each entry carrying
  its provenance in comments.
- **Not done, deliberately:** herdr pane-state annotation —
  seats are not herdr-hosted until K3a, so there is no pane
  state to read; when hosting lands it will be recorded as an
  advisory annotation only, never as the basis of a blocked
  classification (this track's classifications are ours alone,
  per the K2 spec).
- Guard/test updates that ride along: the v14 subprocess
  guard accepts the supervised seat wait as a Popen pairing
  (it enforces the same timeout as a deadline + tree kill);
  one scripted-wizard test pins PATH so host-installed CLIs
  cannot add prompts to its script.

### 2026-11-05 (empty-content failure class)

- **Seat `ProviderError(kind="empty")` is now a content-class
  failure in the bench generation layer**
  (`bench/generation.py`). The DeepSeek soak (2026-11-05)
  reproduced the class on 5/24 bench calls against a healthy
  account — the provider answers with an empty content
  channel, its completion budget spent in the reasoning
  channel. Previously the generation layer classified it
  "unknown" (transport class) and latched the seat exhausted,
  losing the report as infrastructure noise. Now the seat
  records a `content_invalid` event (error class `empty`) and
  hands the failure to the product's own retry behaviour as
  the re-draw, with the pre-declared per-lens fallback seat
  next — no transport-budget burn, no latch. The raw
  empty-body transport return stays transport class; all
  other mappings unchanged. Equivalence-checked against the
  pre-change tree on public-split scripted scenarios
  (identical except for `kind="empty"` outcomes); 4 new
  parent-fail-verified tests. Detail:
  `bench/VOID-SOLUTION-FINDINGS.md` ("Empty-content class
  fix"). No change to policy B1, thresholds, metric
  definitions, gate semantics, or the confirmation scorer.

### 2026-11-05 (void solution: generation machinery, S1, S4)

Implements the machinery of the adopted post-void solution
(`codereview-baseline-v2-void-solution-2026-11-05.md` §3) plus
findings S1 and S4 from its §6. Findings status: **S1 fixed**
(this entry), **S4 fixed** (this entry); **S2 and S3 are handled
by the registration-addendum track, not here.** Nothing here
changes policy B1, any threshold, any metric definition, or the
confirmation scorer.

- **Generation/scoring separation for the bench**
  (`bench/generation.py`, driver
  `bench/scripts/run_generation_v2.py`): seat responses are
  generated per case x seat through a record/replay cache keyed
  by (seat, model, params hash, prompt hash). Transport errors
  are never cached; the first valid response (valid = the
  product's own parser accepts it) is cached and never
  re-drawn. Failure classes per §3.2: transport/infrastructure
  failures retry with backoff + jitter inside a per-job attempt
  cap and wall-clock budget and are not degraded when a valid
  response lands; content failures follow the product's own
  repair behaviour and then the pre-declared per-lens fallback
  seat (healthy when the fallback serves, `served_by` /
  `fallback_for` recorded); a seat unserved beyond budget marks
  the case `unscored-infra`. Generation is resumable — a run is
  complete when every case x configured seat has a valid
  response — and the frozen attempt file holds complete cases
  only. The committed confirmation scorer consumes the output
  unchanged (adapter: `generation.to_attempt_record`).
  Generation records carry per-case failure counts, and
  `bench/scripts/analyze_failure_features.py` implements the
  §3.2 post-hoc guard (failures/retries vs diff size, language,
  defect/clean).
- **S4 — cost is metered, not declared:** the generation path
  records tokens per job and shadow-prices them from a list
  price table (labelled shadow/approximate in the code and the
  run manifest); attempt records from this path carry the
  metered `cost_usd` instead of the `cost_per_call_usd: 0`
  convention.
- **S1 — lenses bind to seats explicitly (product fix):**
  `core.run_review(..., seat_lenses={seat: lens})` binds each
  seat to its lens in panel config. Excluding a seat leaves its
  lens unserved — served by the lens's configured fallback
  (recorded with `fallback_for` naming the absent seat) or the
  run is degraded with a "lens unserved" cause and cannot PASS
  — never a silent remap onto the surviving seats, which is
  what confirmation attempts 3–4 did. Bench configs accept
  `seat_lenses`; configs without one get the binding derived
  once at load from the provider order (the historical rule,
  recorded on the loaded config and in each report's
  `seat_lenses` section). Config identity: an explicit binding
  joins the config hash; a derived one does not (it is a pure
  function of the provider list already hashed, so pre-S1
  config hashes — and their stored records — are unchanged).
- **Verification-round fixes on the generation driver** (the
  internal review blocked this branch on one major + four
  minors; all fixed, detail in
  `bench/VOID-SOLUTION-FINDINGS.md`): the registered-set guard
  now refuses every non-public split by name — holdout,
  expanded-clean, any future split — before any seat call,
  unless `CODEREVIEW_REGISTERED_RUN=1`; fallbacks are validated
  at driver entry (panel membership; under an explicit binding
  a fallback may not reassign a lens to a different seat) and
  the effective fallbacks join the run's identity in the
  generation manifest; budgets are stated and enforced as one
  model — a 600 s per-job wall-clock cap inside an 1,800 s
  per-case budget (per-seat case deadlines in
  `bench/generation.py`).

### 2026-11-05 (Epic K1: setup CLI discovery)

First-run setup now looks at the machine before asking for
provider specs (`src/codereview/discovery.py` + the wizard's
discovery step). It scans PATH for the agent CLIs the product
already knows how to seat — Claude Code, Codex, Gemini CLI —
reports each found binary with its resolved path and a cheap
`--version` probe outcome (failures are printed as failures,
never smoothed over), and offers the ones carrying a verified
non-interactive invocation as panel seats: "they review using
your existing CLI logins, no API key needed." Today exactly one
invocation is verified in-tree — Claude Code's, the shipped
example wrapper's `claude -p --tools "" ...` — so Codex and
Gemini CLI are reported as found but not pre-filled, until a
probe-verified template enters the table (spec U6). A confirmed
pick saves an ordinary `agent:<name>:<command>` spec through
the existing save path; declining everything leaves the flow
and the saved config byte-identical to before. When discovery
contributes seats, a family-diversity check warns in plain
words if the confirmed panel covers a single vendor family
and offers one API spec as the second family (never blocks
saving). Non-interactive runs are untouched: no setup still
stops with setup instructions. Tests:
`tests/test_discovery_wizard.py` (22; fake PATHs/stub
executables throughout, plus a hermetic end-to-end where a
discovered stub seat serves a real review).

### 2026-11-05 (step-3 error persistence)

Implements step-3 recommendation 3 of the void forensics
(`void-forensics-2026-11-05.md`): the bench record writer used
to trim reviewer reports to provider/lens/status/attempts,
dropping the seat error string — the voided confirmation
attempts' exact failure classes were unrecoverable from their
records. Additive only; no change to policy B1, thresholds,
metric definitions, gate semantics, or the confirmation scorer.

- **Errored reports now persist their failure detail** on every
  record-writing path. Reviewer reports carry `duration_ms`
  (wall-clock of the call) and `prompt_chars` (prompt size in
  characters), and an errored report — or one whose primary
  failed before a fallback served — carries an `error_detail`
  block: the FULL error string, its `http_status` (parsed from
  the error by `core._http_status_of`; `null` when the error
  carries none — never invented), the failure classes, and the
  fallback's error/status when a fallback also failed.
- **One shared persisted form**: `core.reviewer_report_entry`
  is now used by both the bench result writer
  (`src/codereview/bench.py`) and the generation attempt-record
  adapter (`bench/generation.py`), so no writer trims a report
  on its own. Generation per-case records fold each failure
  event's detail (error string, HTTP status, duration, prompt
  size) into an `error_detail` list, and generation events keep
  up to 2,000 chars of an error's text.
- **Legacy records are unaffected**: no record hash covers
  reviewer reports, readers treat a missing `error_detail` as a
  legacy record, and the shipped v1 baseline results still load
  (pinned by test).

### 2026-11-05 (acceptance wiring, protocol v2)

- `acceptance.run_acceptance_v2`: the redesigned Tech Lead
  (techlead.adjudicate) can now be scored over the acceptance
  corpus through the SAME scorer and metric computation as
  the v1 runner (`_scorecard_metrics`, shared). V2 entries
  are mapped by `adapt_v2_entry` field-for-field; the
  two-field reasoning assessment the machinery stratum
  scores is the seat's own (the v2 verdict draw now returns
  it in the v1 vocabulary) — never derived by the adapter.
  Per-path results (deterministic probe path vs model path)
  are reported separately in the run record, never blended.
  M1 follows the scorecard's counting rules (by scored
  decision); the scorer's per-case false_dismissal flag is
  vestigial and unused. M4 is not run in v2 baseline mode.

### 2026-11-05

- Baseline v2 confirmation (step 7): VOID — no counting attempt
  completed. The pre-registered confirmation of policy B1 on the
  A5 holdout + expanded clean stratum was started six times on
  2026-11-05; every start was voided or aborted on
  provider-environment grounds (the DeepSeek seat errored in
  every degraded case; the NVIDIA free tier was quota-dead at
  three preflights; Gemini dead at every preflight, excluded as
  in the v1 baseline). No confirmation metric was measured and
  no pre-registered threshold is met or failed; B1 remains
  unconfirmed and the default gate profile stays `strict`.
  Attempts consumed under the registration: 0 (voids do not
  count); the sets remain unconsumed under the same
  pre-registration. Full accounting:
  bench/BASELINE-V2-2026-11-05.md (the standing quotable baseline
  remains bench/BASELINE-2026-11-04.md).
- Gate profiles (step 6 of the adopted honest-negatives
  solution; candidate frozen by the step-4 replay sweep):
  policy B1 (per-lens corroboration) ships as the `balanced`
  gate profile. A blocking-severity finding whose merged
  sources are solely the operations lens — no
  correctness-lens or deterministic corroboration within the
  gate's merge identity — is demoted to a visible minor
  before archived/fixture/precedent/platform classification
  and before cross-family confirmation; the demotion and its
  reason are recorded on the finding (`profile_demotion`)
  and in the record's `gate_profile` section (effective
  profile, its source, every demotion). Selection:
  `--gate-profile` flag, else the policy file's new `[gate]
  profile` key, else the default. **The default remains
  `strict`** — today's behaviour exactly — under the freeze
  terms: B1 is confirmed once on the holdout in step 7
  (Baseline v2) before any default change. Findings now
  record per-source lens attribution (`source_lenses`,
  unioned by the merge; an unattributed source fails safe
  and is never demoted on a guess) and evidence-class
  metadata (E0 deterministic / E1 corroborated / E3
  single-seat unverified; E2 probe-confirmed is not assigned
  at gate time, since probes run in adjudication) — the
  classes change no verdict under `strict` and act only
  through B1 under `balanced`. **`quiet` is not implemented,
  by decision**: its blanket-corroboration form was rejected
  on the sweep evidence (it demoted three real single-seat
  majors, D6–D8), and naming it — CLI, policy file, or API —
  is a loud error, so the absence is a recorded decision,
  not an omission. Expected effect, quoted AS REPLAY
  (step-4 sweep, public split, adjudicated semantic
  grouping; live merge-identity grouping sits between strict
  and this row): blocking recall 29/34 enlarged (24/24
  labelled), merged blocking precision 1.000 excl. unknowns
  (0.967 incl.), clean-case BLOCKED 0.20 vs strict's 0.40.
  A claim-lint test (tests/test_claim_lint.py) now fails if
  the README, this CHANGELOG, or the baseline
  (bench/BASELINE-2026-11-04.md) quote the headline figures
  without the baseline's `required_caveat` adjacent, or
  present the superseded naive figure as a current claim.
  31 new tests (suite 802).
- Tech Lead redesign, adjudication protocol v2 (branch
  `tl-redesign`; honest-negatives solution §3.3 + §3.5,
  owner decision 2026-11-05 to proceed despite the §3.7
  tally): new module `src/codereview/techlead.py`, protocol
  v1 (`core.shadow_adjudicate`) untouched and still the
  wired shadow path. The v2 seat returns verdict +
  calibrated confidence + deciding quote only — "escalate"
  and "needs_probe" are invalid outputs; the harness
  escalates on exactly six named rules (protected class,
  independence, draw disagreement, evidence ineligibility,
  major dismissal without probe support, low confidence),
  each recorded on the entry. Settling probes decide on a
  deterministic path where the seat only grades probe
  adequacy; the two paths are reported separately, never
  blended. Packets are canonicalised (vendor/family
  scrubbed, content-keyed position order), so vendor-strip
  and family-swap invariance holds BY CONSTRUCTION and is
  labelled as such. Double draw is canonical + swapped;
  majors always draw twice. Judging frame is AS RAISED —
  a fix shipped in response to a finding supports it
  (FIX_SHIPPED settles to sustain_finding; the L06
  inversion is structural now). Dismissal-quote eligibility
  consumes `core._dismissal_quote_check` from the harness
  fixes (call-time resolution, grounding-only fallback
  labelled on the record). Every entry carries its §3.5
  authority stage (1/2/3/never); `ENABLED_STAGES` is empty
  — hooks built, nothing flipped, no acceptance or
  evaluation run made. 47 new tests (suite 759).
- Issue 2 (benchmark precision) CLOSED by the measurement path
  (owner act): blind probe-first adjudication of all 91 unmatched
  findings — 64 duplicates, 10 real unlabelled defects (added to
  ground truth), 7 true false positives. Corrected semantic
  precision 0.870 finding-level / 0.756 merged (blocking 0.956 /
  0.906); the baseline's required_caveat carries the corrected
  figures and the naive figure is superseded. Behaviour work
  (policy profiles, corpus expansion, Baseline v2) continues.
- Harness fixes from the honest-negatives step-2 forensics
  Part A (branch `harness-fixes`; no Tech Lead redesign, no
  gate change, no acceptance re-run): (1) the
  dismissal-evidence rule is enforced in shadow draws (L06)
  — a dismissal's deciding quote must be distinct from the
  refutation's quote and pass a deterministic relevance
  screen against the claim, or the dismissal is
  evidence-ineligible and escalates; the acceptance scorer
  applies the same full check. (2) Cited-line discipline
  for presented regions (P06) — `locate_presented_region`
  prefers the anchor window containing the finding's cited
  line, centres on the cited line when no anchor window
  contains it, and marks `region_unverified` when the line
  cannot be placed; the corpus builder delegates to it
  (P06's inputs now locate at 938–954, the actual defect,
  instead of the sibling at 609–625), and
  `acceptance.case_inputs` flags inputs whose stored region
  is verified by neither the cited line nor the finding's
  grounded quote (9 of 48 shipped cases, P06 among them),
  carried loudly on the shadow entry.


## 0.12.1 — 2026-11-05 — acceptance fixes

Patch release from the clean-room acceptance test of the built
0.12.0 package (verdict: READY-WITH-DEFECTS). The planted defect
was caught precisely and the first-run, policy, evidence and
record-verify surfaces behaved as designed, but a clean, correct
change could be BLOCKED by confident false findings. 0.12.0 was
never published to PyPI (tag only); the corrected build ships
as 0.12.1. Suite 870.

- **D1 — file context on the standard diff path:** reviewers
  previously received only the plain unified diff (3 lines of
  context), so definitions outside the hunk were invisible and
  correct code drew false "undefined symbol" majors from two
  model families at 0.98 confidence. The diff path now attaches
  the post-change contents of changed files, with per-file and
  total caps, in-text truncation markers, and the context budget
  allocated to the most-changed files first. `run_review` gains
  `file_context=None` — bench and registered-run prompt shapes
  stay byte-identical by default; the acceptance clean case now
  reaches PASS while the planted defect still BLOCKs.
- **D2 — stored error type/status:** seat error strings stored
  in run records now preserve the HTTP status and exception
  type instead of truncating mid-token, so a rate limit (429)
  is distinguishable from a crash in the record.
- **D3 — `--help` subcommand list:** top-level `codereview
  --help` now lists the subcommands (setup, policy,
  record-verify, doctor, …) instead of leaving them
  discoverable only through the README.
- **D4 — same-line finding merge:** identical findings raised
  by two seats on the same line are merged into one finding
  listing all raising seats, and the gate counts it once.

## 0.12.0 — 2026-11-04 — the finish release

The clean-gate hold is LIFTED by the owner on an eligible Form B chain
(complete-coverage round 1 over 3013656..2fbf94f + 2 verification
rounds; record-verify --chain 12/12, exit 0). Suite 691.

- Dispute machinery: computed inventory (codereview disputes),
  append-only disposition store (116 owner-ratified entries),
  authority-affecting tagger, quote-anchored locate, release-flow
  freshness check in record-verify --chain.
- Epic A benchmark + first quotable baseline: recall 24/24 on the
  public split (Wilson 95% lower bound 0.86), escaped-defect rate
  0.000; deterministic layer alone recall 0.458. Precision: the
  naive one-to-one figure as first published (superseded the
  same day by the adjudicated recount — never quoted; the
  corrected figures are in the measurement-repair addendum,
  bench/BASELINE-2026-11-04.md §6; the naive count's other
  rows: blocking-tier 0.267, merged-finding 0.727 with 82
  duplicate matches removed); clean-case BLOCKED rate 0.40 (2/5) and
  clean-case any-finding rate 0.60 (3/5) are the stated caveats —
  corrected figures in the measurement-repair addendum,
  bench/BASELINE-2026-11-04.md §6 (adopted solution §2.2).
- Epic B policy file, Epic C evidence runner, Epic D1 SARIF export.
- Probe harness (sandboxed, rebut-only) + shadow Tech Lead (full
  adjudication schema, A/B blinding, double-draw). Acceptance run
  EXECUTED: unlock NOT earned (M1/M2/M3/M4/M6 fail; M5 pass) — the
  Tech Lead remains shadow-only.
- Verify mode repaired: archived-aware sectioned prompts and
  batched (never truncated) prior findings.
- Renderer gate line states the degraded cause; duplicate-seat
  record fidelity; prompt-slice truncation markers inside the cap.

### process tooling (branch `process-tooling`)

Implements §5 of the adopted open-refutations solution
(2026-11-04): the computed dispute inventory, the append-only
disposition store, the release-flow freshness check, the
deterministic authority-affecting tagger, and quote anchoring.

- **`codereview disputes`** scans all `review-*/` records (plus
  evidence sidecars) and prints the open-dispute inventory —
  findings with status `disputed` or `refutation_weak` and no
  disposition in the store — grouped by record with lens,
  raiser/refuter families, and the authority-affecting tag;
  `--json` for tooling. Run summaries now carry `open_disputes`
  (count + fingerprint list).
- **Disposition store** `dispositions.jsonl` (repo root,
  append-only): entries carry the fingerprint, type
  (`sustain_refutation` / `sustain_finding` / `split` / `fixed`
  (requires the fixing commit) / `retired_archived_subject` /
  `retired_out_of_scope` / `superseded` / `downgraded`), decider
  (`owner` / `tech_lead` / `probe`), date, the reasoning-quality
  fields `reason_check` / `reason_corrected` / `basis_evidence`,
  and a `ratified` / `override` marker. `codereview disputes
  --record <entry.json>` appends with validation: a fingerprint
  is dispositioned once, unless the new entry is an override
  naming the entry it supersedes. `record-verify` consults the
  store automatically when present (a disputed finding with an
  entry counts as dispositioned; consumed entries are named);
  with no store, verification is unchanged.
- **Freshness check:** `codereview disputes --check --span
  A..B` exits non-zero listing any dispute in records touching
  the span that is neither dispositioned nor listed in a
  caller-supplied `--inventory` file. Documented in the README
  as the release-flow gate; intentionally not wired into any
  automated script.
- **Authority-affecting tagger** (deterministic, §5.5): the
  former "protected class", defined as findings that could
  change who decides, whether independence holds, whether a
  precedent/decision is valid, whether eligibility passes, or
  what leaves the machine. Report rendering and prompt display
  truncation are explicitly excluded; a manual override list
  wins over the rules.
- **Quote anchoring** (§5.6): findings gain `line_basis`
  (`blob` / `diff`) when the cited line and quote determine one
  numbering; deterministic findings are `blob`. `codereview
  locate <finding-id> --record <path>` resolves a finding's
  validated quote (sidecar full text when truncated) to its
  blob position(s) at the reviewed commit; legacy findings
  without a basis still locate by quote.

### Epic B: project policy file
Built on the `epic-b-policy` branch off v0.11.1; not yet merged or released. Implements Epic B of the adopted roadmap (`codereview-revised-plan-and-engineering-roadmap-2026-11-04.md` §11). The announcement hold is untouched.
- **B1 — `.codereview.toml` schema (`src/codereview/policy.py`, new)**: the repository's own review contract, parsed with stdlib `tomllib` only — `[panel]` (min_seats, min_families, required_families, require_lenses), `[evidence]` (require_tests, require_tests_pass), repeatable `[[paths]]` rules (match, require_full_panel, require_tests, require_tests_pass, min_seats, min_families, enforce = block|advisory), and `[waivers]` (allow, require_reason, max_age_days). Every key is optional and the defaults are the documented no-requirement values, filled into an effective-policy dict that also records the file's path and sha256. Validation is strict (unknown tables/keys, wrong types — a TOML bool is not an int — negative counts, unknown lenses, a `[[paths]]` entry without `match`) and every error is line-referenced: TOML syntax errors carry tomllib's own line, semantic errors locate the offending key in its table. This is the PROJECT's policy, a different thing from the per-user setup config (`userconfig.py`), which only stores a person's provider specs.
- **B2 — the gate reads policy**: `core.run_review(..., policy=..., waivers=...)` evaluates the loaded policy against the round's facts (changed files, reviewer reports, test results, recorded waivers) via the pure `policy.evaluate_policy` (path semantics are the engine's own `path_matches`, passed in — one implementation). The record gains a `policy` section listing every rule that applied (with satisfied/violated status) and every violation; violations join the gate reasons, and a blocking violation turns a PASS into BLOCKED (an INCONCLUSIVE round stays inconclusive, violations on the record). Advisory path-rule violations are recorded, never gate-changing. `render_markdown` shows the policy line and its violations. The CLI review command discovers `.codereview.toml` at the repo root or takes `--policy PATH`; an invalid file stops the run. Scope note: verification rounds (`--verify-previous`), `pr`, and `loop` do not take a policy yet.
- **B3 — `codereview policy check`**: validates the discovered (or `--policy`-named) file and prints the effective policy with defaults filled in; with no file it prints the defaults and says so (a valid state, exit 0); an invalid file exits 2 with the line-referenced error.
- Suite: 449 tests (49 new in `tests/test_policy.py`: loader validation + line references, per-rule evaluation incl. waiver ageing, gate integration with fake panels, and the CLI surface). Full suite green.

### Epic C: evidence runner (branch `epic-c-evidence`)

The evidence runner (roadmap Epic C, Week 2): the deterministic counterpart to the reviewer panel. Reviewers judge a diff but cannot run anything; the evidence runner executes the project's own configured commands and security adapters against the change, stores a content-hashed record in the run JSON, and makes required evidence a first-class gate input. The announcement hold stays ON; nothing here is a closing attempt.

- **C1 — `codereview.evidence` (new module) + `collect()`**: configured commands (tests, lint, SAST) execute in a sandboxed working copy of the tree; every item records status (`passed`/`failed`/`timeout`/`unavailable`/`missing`/`error`), exit code, duration, the sha256 of its full output, and a redacted output tail. Timeouts are enforced by killing the child's whole process group. Attached to a review via `--evidence-config`, the record is stored verbatim in the report under `evidence`.
- **C2 — adapters**: `gitleaks`, `semgrep`, and `dependency-audit` (first available of osv-scanner / pip-audit / npm-with-package.json), resolved against the caller's PATH and run through the same sandbox executor. A missing tool is recorded `unavailable` with the reason — never a crash. A config `require` list records policy-demanded-but-unconfigured evidence as `missing`: the mechanism by which a policy requires a tool's presence. The config dict shape deliberately mirrors the Epic B policy file's `[evidence]` table (B1), so a `tomllib`-parsed policy section can be handed to `collect()` unchanged when Epic B lands.
- **C3 — gate rule**: required evidence failed / timed out / errored / missing ⇒ **BLOCKED**; required evidence unavailable ⇒ **INCONCLUSIVE** (the machine could not produce the evidence — not the builder's failure). Implemented as the pure `evidence.gate_effect()` over the item list and applied in `run_review` after every other gate adjustment; it can only move a gate toward blocked/inconclusive, never clear anything. Optional evidence is recorded and never moves the gate.
- **C4 — builder-claim verification**: `parse_claims` extracts the claims a builder work report actually commits to (backtick-quoted command + outcome on the same line, or a labelled `Tests:`/`Ran:`/`Command:` line with the outcome in its tail; outcome words inside the command itself never count, and commands without a claimed outcome are ignored, never guessed at). `verify_claims` re-runs each claim in the sandbox and compares exit outcomes: matching claims are `confirmed`; contradicted claims are **downgraded** in the record with claimed vs actual outcomes stated. Standalone surface: `codereview evidence --claims report.md`.
- **C5 — sandbox safety, with the threat model documented in the module and the README**: commands run in a throwaway copy of the tree (`.git` excluded, symlinks never dereferenced during the copy, copy deleted after the run) — never in the reviewed checkout; the child environment is built from an allow-list (no provider API keys, tokens, or SSH agent; HOME/TMPDIR inside the sandbox); no network by default (proxy variables stripped; a Linux user+network namespace via `unshare -rn` where available — the record states `namespace` vs `env-only` honestly, and an item must opt in with `allow_network: true` to run unrestricted); POSIX rlimits (CPU time, per-file size) recorded in the record's `sandbox` block. Output tails pass through the review path's own `redact_secrets`, so a scanner that prints the secret it found cannot smuggle it into the record.
- Suite: 435 tests (35 new in `tests/test_evidence.py` covering every ticket: record/hash/duration, timeout enforcement, copy isolation, env scrubbing with an operator marker that must not cross, honest network-mode recording, adapter present/absent/failing via fake tools on a test PATH, policy `require` → `missing`, every gate state as a pure function and end-to-end through `run_review`, claim parsing forms and downgrade-on-contradiction, claims verified inside the sandbox).
- Example config: `examples/evidence.json`.

## 0.11.1 — 2026-11-04
The v0.11.0 fix step: dispositions the standing items of the v0.11.0 internal review (record `review-v110/codereview-20261105-001944.json`, BLOCKED as received) — one deterministic blocker, one major, two minors, each cited by finding ID below. Nothing here adjudicates any disputed or refutation-weak finding; the owner's protected-class queue (nine items) is untouched, and the announcement hold stays ON.
- **Blocker `44a6ae2d215a` — closed durably; the deterministic rule is NOT weakened.** The hardcoded-secret rule fired for the third time on a test fixture's fake key value — this time the `DEEPSEEK_API_KEY` fixture at `tests/test_user_setup.py:97`. The in-branch rename (`98ad1d9`) had removed the key-prefix shape but not the assignment shape the rule reads, which is why it re-fired; the correction to the v0.11.0 disposition bullet recorded in `0ba2c17` stands, is not rewritten, and this release is the fix it pointed at. Instead of renaming one string again, the whole fixture surface was audited and the class closed: **every string neutralized** (the full `tests/` tree scanned against the three deterministic secret rules plus bare key shapes) — (1) `tests/test_user_setup.py`: the fixture value `sentinel-value-never-stored` → `placeholder-deepseek-key-never-stored`, carrying the scan's own placeholder exemption token so the rule can never read it as a secret (the test's assertion — the value never reaches the saved config — is unchanged); (2) `tests/test_core.py`: the scanner/redaction fixture value is assembled at runtime from fragments (`FAKE_KEY_VALUE`, with a short placeholder token inside the `BUGGY` patch replaced at build time) — the runtime value is byte-identical, so the scan and redaction assertions are unchanged, but no literal line matches; (3) `tests/test_external_review_v070.py`: the agent-env fixture value likewise assembled from fragments (`FAKE_OPENAI_VALUE`), runtime value identical. **Audited and left as-is:** `ghp-test-SECRET` (`tests/test_external_review_v070.py`) — a hyphenated test marker that matches no secret pattern (GitHub's token shape is `ghp_` + alphanumerics). **Regression guard:** new `tests/test_fixture_secret_hygiene.py` runs the product's own deterministic scan (with its placeholder exemption) over every line under `tests/` presented as added diff lines — exactly what a review of a test-suite change sees — plus a bare key-shape scan; a fourth firing now fails the suite instead of surfacing in a review. Negative control verified: all three historical fixture shapes trip the guard.
- **Major `3bbe648d8bfc` — doctor probe calls are wait-bounded.** `run_doctor` called each seat synchronously with no bound; a seat whose callable hung (a transport with no ceiling of its own) blocked the preflight forever. Probes now run through `_probe_call_bounded` — the same daemon-thread wait bound the review path gives reviewer / Tech Lead calls (`_review_job_bounded`) — with the same default semantics: `timeout=None` resolves to `TECH_LEAD_CALL_TIMEOUT`, and a non-positive timeout is a caller error (ValueError before any seat is probed). `codereview doctor --timeout` now also sets the probe bound (it already forwarded to agent-seat construction). A timeout surfaces as a failed seat (`error_class: transient`, "timed out" error), never a hang. Tests: `DoctorTimeoutTests` — hanging seat bounded and reported, fast seat unaffected, default-ceiling semantics, non-positive rejection, `_doctor_main` wiring.
- **Minor `a509b806fda6` — the wizard's provider loop has a retry bound.** `MAX_PROVIDER_ATTEMPTS = 3` invalid or empty provider entries; exhausting the bound aborts through the same EOF channel as an EOF at any prompt (message printed, nothing saved, clean exit). Tests cover exhaustion (aborts, no config written) and recovery within the bound (bad entry, empty entry, then a valid one proceeds).
- **Minor `84fc41a76d3f` — duplicate-role coverage for the lens roles.** `parse_role_assignments` already rejected a role assigned twice, but the only duplicate test used a non-lens role. Added explicit coverage for the dangerous case: a duplicated lens role (`correctness`, `operations`) is rejected at parse, and through `_apply_role_assignments` the rejection lands before any seat is built or merged — the panel is left untouched and no lens pin is recorded.
- Suite: 400 tests (10 new: 1 fixture-hygiene guard, 5 doctor-timeout, 2 wizard-bound, 2 duplicate-lens-role).
- **Internal review of this diff (verdict as received — no PASS is claimed)**: **INCONCLUSIVE**, not degraded, coverage complete, the record's own test run green (400 tests); **zero standing findings and zero deterministic findings** — blocker `44a6ae2d215a` did not fire on this diff, the outcome the hygiene guard exists to make permanent. Gemini quota-failed on the batch (not retried); the OpenAI fallback served correctness, NVIDIA operations. One **refutation-weak major** is recorded exactly as received: `a1982210ce99` (OpenAI-raised, NVIDIA-refuted) claims the `test_user_setup.py` fixture "still sets the old redacted value while the test asserts against a different string." Builder evidence, recorded without adjudicating: in the committed tree the assignment and the `assertNotIn` carry the identical placeholder string and the wizard test passes against it; the panel could not see that, because the product's own redaction rewrites any `KEY="…"` value to `[REDACTED]` before a diff leaves the machine — both the claim and the refutation reasoned from the redacted text, and the refutation's quote is the redacted line itself (hence weak adequacy). The finding therefore turns on what the evidence pipeline shows the panel, so it is flagged a **protected-class candidate** (evidence/redaction machinery) and joins the owner's ruling queue (now ten) exactly as recorded; no independent Tech Lead served (two families live), so the human gate decides. `record-verify` on the record passes every recomputation (patch hash, range, head currency, 6 evidence refs against their sidecars, lens coverage, two families) and fails only `gate_pass`, because the gate is INCONCLUSIVE. Record: `review-v111/codereview-20261105-003107.json`.

## 0.11.0 — 2026-11-04
The user-configuration release: the `role-model-choice` branch (built in parallel in an isolated worktree) merges onto v0.10.0 — per-role model choice, a provider registry covering all major LLM providers, and first-run setup with NO shipped default panel (owner directives 2026-11-04). This release also mints the owner's 2026-11-04 sustained-refutation rulings into the precedent store. No closing attempt ships in this release; the Tech Lead gains no binding authority here — the probe harness and shadow-mode upgrade remain the next track. The announcement hold stays ON.
- **Provider registry (`src/codereview/registry.py`, new)**: the single source of truth for provider presets — OpenAI, Anthropic, Google Gemini, DeepSeek, MiniMax, Moonshot (Kimi), NVIDIA NIM, xAI, Mistral, OpenRouter, a generic `openai-compatible:<base-url>` escape hatch, and agent seats. Each preset carries its base URL, key env var (bring-your-own-key; the product never supplies or stores a key), suggested model, **family tag** (feeding the Tech Lead independence check and the record), and request quirks (e.g. models that reject a sampling temperature get none sent — the gpt-5 lesson, encoded per preset). The seat builders in `providers.py` read family/kind from this registry, so a seat's family is a build-side fact, never a self-report.
- **Per-role model choice**: `--role <role>=<provider-spec>` (roles: correctness, operations, verifier, tech-lead, solver) assigns the user's preferred model to each role; lens roles pin their seat in `run_review` (`lens_seats`), and the Tech Lead designation flows through the step4 seam. The record carries `seat_roles` and `role_models` (seat, provider, model, family, key env per role) — any verdict shows exactly which model served which role. With no assignment, the panel behaves exactly as before this release.
- **First-run setup — no default panel (owner amendment, mid-build)**: `codereview setup` (new `userconfig.py` + `setup_wizard.py`) is an OpenClaw-style first-open flow: pick providers, name the key env vars (the wizard never asks for, echoes, or stores a key value — the saved config references env var names only), assign a model per role, save as YOUR defaults (`$CODEREVIEW_CONFIG`, else `$XDG_CONFIG_HOME/codereview/config.toml`). Provider resolution order is config-first: explicit `--provider` flags → `$CODEREVIEW_PROVIDERS` → the saved setup → (interactive TTY only) the wizard → stop. An unconfigured non-interactive run exits 2 with setup instructions; it never silently reviews with a built-in panel. Our internal Gemini/NVIDIA/OpenAI panel exists only as our own saved setup in the internal runner, never as a product default.
- **Hand-merged integration seams (merge `96bfe03`)**: `core.run_review` keeps BOTH the step4 adjudication keywords (`tech_lead`, `probe_fn`, `tech_lead_timeout`) and `lens_seats`; `cli.py` composes `precedents` + `tech_lead_timeout` + the role `review_kwargs` at the review call, with the explicit `--tech-lead` flag taking precedence over a `--role`/saved-setup designation of the same role (command line beats config, as `--role` already did). The branch's one adapted test (`tests/test_v090_fixes.py`) carries over. Merged suite: 390 tests, green.
- **Dispositions of the providers branch's own review residue — recorded honestly, nothing adjudicated by the builder**: the branch's two internal reviews (records in the branch worktree, `review-providers-out/`, `review-providers-out2/`) left the following. (1) Deterministic **blocker** `44a6ae2d215a` ("possible hardcoded secret in added code") fired on an `sk_live_…` fixture string in the wizard tests; it was **fixed in-branch** (`98ad1d9`, the sentinel renamed) and the merged tree is verified free of the pattern — the finding stands as recorded, a true positive against the fixture text at review time. (2) Refutation-weak major `19a537eb386b` (a role assignment could record the wrong seat, then crash on duplicate provider names) was **hardened in-branch by change**: `_apply_role_assignments` refuses loudly when a role seat's name is already owned by a seat of the other kind with proven tags, and build-side family tags remove the ambiguity the claim cited — addressed by change; the finding stands as recorded. (3) Refutation-weak major `931ea3882b76` (aborting the interactive first-run wizard crashed the review command) was **partially fixed in-branch** (`98ad1d9`: EOF/Ctrl-C at the wizard is caught at the `main()` call site and exits cleanly at 2); any remainder is recorded as-is. (4) Minor `353eaa52d669` (the wizard would re-trigger on every TTY first-open without checking for an existing setup) is answered by the config-first resolution above: the wizard branch is reached only when flags, env, AND the saved setup all yield no providers — the rebuttal the branch record carries, cited here, not adjudicated. (5) Two **disputed majors stand exactly as recorded**: `3d9645200bc5` (family tag not set for seats built from custom/openai-compatible specs without a registry entry) and `e1e22d48db4d` (`build_providers` does not apply the model override from a `preset:model` spec). Both touch the family/seat machinery, so both are flagged **protected-class candidates** and join the owner's ruling queue behind the three items from the v0.10.0 review (`4ce0212286e0`, `6b29fe953939`, `bf4c451e8751`) — the queue now holds five.
- **Precedent store: the owner's 2026-11-04 rulings minted (store 5 → 19 entries)**: the 12 review-v15 sustained refutations (rulings addendum, v15 closing-run report) and the 4 step4 protected-class sustained refutations (refutation-process report) were converted with the v0.10.0 function-level tooling at HEAD (`upsert_precedent`), each entry citing its ruling source. 14 entries minted: 13 function-keyed to exactly the function each ruling concerns (`run_bench`, `percentile`, `main`, `_doctor_main`, `path_matches`, `run_verification`, `_parse_agent_spec`, `build_providers` ×2, `apply_precedents`, `_precedent_candidate`, `_select_tech_lead`, `_seat_meta`) and 1 file-keyed (`2242edbba9c9` — a module-scope imports claim with no enclosing function; the import block and `_kill_tree` were diff-verified unchanged since the ruling). Live check: re-raised claims classify `standing` at function and file scope; the precedent suites pass. **Two exceptions, not forced**: `3c39c4bdc15a` and `2fa2b04e08d5` cite CHANGELOG.md lines whose disposition text has since moved in a living changelog (the disposition blob no longer exists at the cited lines) and function keying does not apply to Markdown — the tooling cannot express them faithfully, so no entry was minted; the rulings themselves stand in the v15 report.
- **Internal review of this diff (verdict as received — no PASS is claimed)**: **BLOCKED**, not degraded, coverage complete, the record's own test run green (390 tests); 2 findings withdrawn in the re-ground pass. Gemini quota-failed on every batch (not retried); the OpenAI fallback served correctness, NVIDIA operations. Standing findings: one deterministic **blocker**, `44a6ae2d215a` again — and a correction to the disposition bullet above is owed: the in-branch rename (`98ad1d9`) fixed the wizard-test sentinel, but the secret rule fired in this review on a different fixture string in the same file, the fake `DEEPSEEK_API_KEY` value at `tests/test_user_setup.py`:97; the merged tree is free of the `sk_live_`/`sk_test` patterns (verified), not of every fixture string the rule reads as a secret. The finding stands as received — a true positive against fixture text, the class the fixture-manifest mechanism exists to classify. One **major** stands (`3bbe648d8bfc`: `_doctor_main` missing timeout guard on provider calls, on the merged `cli.py`) and two minors (`a509b806fda6` wizard provider loop has no retry bound; `84fc41a76d3f` a missing duplicate-role parse test) — all recorded as received for the next fix step, none dispositioned here. Two majors are **disputed** (`f56cd4a0b6c9`, `_apply_role_assignments` seat re-assignment dedup; `e7fc93e0bb77`, `parse_role_assignments` empty-spec handling — both NVIDIA-raised) and two **refutation-weak** (`78ddf4d5ea27`, role assignment binding with duplicate preset seats; `9a4415ddafa6`, malformed roles value raising `AttributeError` — both OpenAI-raised): with only two families live (Gemini down) no independent Tech Lead could serve, so all four route to the human gate exactly as the design prescribes; all four touch the role/seat/config machinery, so all four are flagged **protected-class candidates** and join the owner's ruling queue (now nine: `4ce0212286e0`, `6b29fe953939`, `bf4c451e8751`, `3d9645200bc5`, `e1e22d48db4d`, `f56cd4a0b6c9`, `e7fc93e0bb77`, `78ddf4d5ea27`, `9a4415ddafa6`). The new machinery exercised itself live in this run: `record-verify` on the record passes every recomputation — 52 evidence refs against their sidecars with 0 dispute-bearing findings lacking complete refs, `precedent_scope_valid` against the new 19-entry store, `fixture_scope_valid`, coverage — and fails only `gate_pass`, because the gate is BLOCKED. Record: `review-v110/codereview-20261105-001944.json`.
- Suite: 390 tests (29 new on the merged line: `tests/test_role_providers.py`, `tests/test_user_setup.py`, incl. fresh-HOME no-defaults and non-interactive refusal coverage).

## 0.10.0 — 2026-11-04
The integration release: the Step 4 machinery branch (`step4-ladder`, built in parallel in an isolated worktree) merges into the main line, its amendment review's two confirmed majors are fixed, and the refutation-process solution's build steps 1–2 land (owner-adopted design: `codereview-refutation-process-solution-2026-11-04.md`). No closing attempt ships in this release; the Tech Lead gains NO binding authority here — the shadow-mode upgrade, probe harness, and known-answer acceptance test are the next track. The announcement hold stays ON.
- **Step 4 machinery merged (`ba4c888` + `15a3958`, merge `bbadad1`; textual merge clean, merged suite 338/338)**: refutation-adequacy routing (§5a.1 — a refutation whose validated quote merely repeats the cited line is graded `refutation-weak`, a routing state, not a verdict); the severity rubric (§5b) in the reviewer/verification prompts and policy (a major requires a demonstrated reachable defect in a supported configuration, with the reachable path cited; no silent downgrades anywhere); the supported-platform manifest (§5c — POSIX, Python ≥3.11, carried on every record and surfaced in the prompt; Windows-only findings deterministically labelled `out-of-scope (documented)`, visible and non-blocking); function-level precedent (§5d — precedent keys on the enclosing function's normalized AST hash plus direct callees, so unrelated edits to the same file no longer re-open settled rulings; legacy file-level entries, incl. the 5 seeded guards, keep working); and **Tech Lead adjudication** (owner amendment superseding the §5a.3 tiebreak): any cross-family refutation — disputed or refutation-weak — goes to a seat whose family neither raised nor refuted it, whose decision (sustain_finding, with rubric downgrade only / sustain_refutation / escalate) is the gate disposition, recorded with rationale, validated quote, family/tier, and all three positions. An ineligible designated seat (`--tech-lead`) is rejected and substituted loudly, never silently; with no independent seat the finding keeps its disputed/weak state for the owner. Sustained refutations and rubric downgrades are precedent-eligible (`precedent_candidates` on the record; persisting stays the caller's step — a run never mutates the store it is verified against).
- **Amendment review fix (a) — Tech Lead call timeout guard (confirmed major `1321bec43a24`)**: adjudication calls ran synchronously inside `run_review` with no wait bound; a hanging seat could block the whole pipeline. `_tech_lead_call` now runs under `_review_job_bounded` (daemon worker thread, hard wait bound, default `TECH_LEAD_CALL_TIMEOUT = 900`s — the panel's per-seat ceiling); `run_review(tech_lead_timeout=...)` threads it and the CLI wires `--timeout` through. A timeout returns `invalid` and the case escalates on the record with the timeout named; the bound in force is recorded per adjudication (`call_timeout`).
- **Amendment review fix (b) — explicit probe-loop bound (confirmed major `f6064fc5e515`)**: the one-probe-round limit was previously an accident of the code's shape. It is now an explicit counter against `MAX_PROBE_ROUNDS = 1` in a loop; a further `needs_probe` escalates with the bound named, and `probe_rounds` is recorded per adjudication.
- **Archived-record exclusion (solution §5.4 / build step 2)**: committed review output (`review-*/` directories) and the `gate-attempts.*` ledger are generated artifacts, not source. Their diff sections are excluded from the reviewed span before batching — reviewers never see them — and every exclusion is listed in the record's `archived_exclusions` with the rule that matched, plus a gate reason. A finding that nevertheless cites archived material (its path is an archived artifact, or its quote exists ONLY inside archived sections — the re-raise shape that produced two of the v0.9.6 review's disputed majors) classifies as archived-text in `archived_text_findings`: preserved, non-blocking, never adjudicated. Verification rounds classify their new findings by the same rule. This kills the re-raise class mechanically, upstream of the whole dispute ladder.
- **Evidence sidecars (solution §4 Q7 / build step 1)**: evidence text is no longer truncated at ingest — finding evidence/quotes, re-ground and cross-family quotes/reasons, Tech Lead outputs, probe records, deterministic-scan evidence, and verification-resolution evidence are all stored full-text (prompt construction slices for display only, in `_finding_public` and the prompt templates). At record-write time, `write_report` stores every such text as a content-addressed sidecar (`<out>/evidence/<sha256>`) and the JSON keeps a display copy (400/300/600-char caps by field) with a `{sha256, length, truncated}` ref per text. Dispute-bearing findings are stamped `evidence_complete` when every position text carries a ref — the flag the Q2 eligibility checklist reads: an adjudication over incomplete inputs is record-ineligible. `record-verify` gains the `evidence_sidecars` check (and `record-verify --chain` its chain-wide form): refs must recompute — sidecar present, hash and length matching, display copy an exact prefix, truncated flag consistent — or the record FAILS; a record with no refs (pre-0.10) reports not-applicable, so legacy records verify exactly as before.
- **Protected-class residue of the branch's own reviews**: the step4 branch's internal reviews left 4 disputed majors (`bb3deba73d59`; `aecd8d6b5f57`, `85ac395128cd`, `24929379e396`), all about the adjudication/precedent machinery itself — a protected class under the adopted design (Q3: the Tech Lead never finally decides its own machinery). They are recorded as disputed, NOT adjudicated and NOT routed to any Tech Lead, and are compiled for the owner's ruling with both positions and code evidence in the release report. The same reviews' one standing minor (`--tech-lead` flag validation, `d4423cae53bf`) stands as received; designation misuse is already rejected loudly at adjudication time by `_select_tech_lead`.
- **Internal review of this diff (verdict as received — no PASS is claimed)**: **BLOCKED**, not degraded, coverage complete, the record's own test run green (361 tests); 5 findings withdrawn in the re-ground pass. Gemini quota-failed on every batch (not retried); the OpenAI fallback served correctness, NVIDIA operations. Standing findings: one deterministic **blocker** — the eval/exec rule firing on the literal `eval(preserved_input)` string inside the new test file's archived-record fixture (a true positive against fixture text, the class the fixture-manifest mechanism exists to classify; it stands as received) — and one minor (the uncapped test-failure `output_tail` in deterministic evidence may carry large outputs). One major stands **disputed** (`4ce0212286e0`, the `_finding_public` prompt-slicing claim) and two majors **refutation-weak** (`6b29fe953939`, function-level precedent callee collision; `bf4c451e8751`, a `write_report` robustness claim) — all three concern the evidence/precedent machinery itself (protected class), no independent Tech Lead served (Gemini was down), so all three are recorded exactly as received for the owner gate; the builder adjudicates none of them. The new machinery exercised itself live in this run: the record carries 21 evidence sidecar files (42 refs, all recomputing under `record-verify`'s new `evidence_sidecars` check, which passes), and the span contained no archived artifacts to exclude. Record: `review-v100/codereview-20261105-000409.json`.
- Suite: 361 tests (23 new in `tests/test_v100_integration.py`).

## 0.9.6 — 2026-11-04
The probe-pack release of the v15-closing-run solution (§4, executed as Step 2 of §6): every disputed major from review-v15 that the solution assigned a probe now has that probe in the suite permanently (`tests/test_v096_probes.py`), so the owner's §3 rulings rest on rerunnable evidence. This release records NO rulings and runs NO closing attempt. Under the owner's adopted §2 rule ("owner rules, builder supplies evidence"), the two v0.9.5 fix-diff disputes are owner-list items #15/#16 (addendum to the v15 closing-run report); the builder adjudication in the 0.9.5 entry below stands as history, superseded as a ruling.
- **Probe results** (probe → disputed finding → outcome): P1 (3c39c4bdc15a) PASS — a free-tier seat behind a local stub endpoint is refused under `--private` before any call (the stub saw zero requests; the control run without `--private` reached it), and a record attesting `private=true` with a successful free-tier seat fails record-verify's `tier_policy` check. P3 (474297e6ffdc) PASS — a forced bench rerun's in-memory records contain none of the stored degraded records (marker cost/timestamp absent; the file is replaced, and the report's `degraded_cases` is 0), and a rerun dying mid-run leaves the previous results file byte-identical (the v12 safety). P4 (09c536d15270) PASS — the doc's property test verbatim in spirit: n 1..59 × pct 0..100 never raises, always returns a member, pct=100 returns the maximum and pct=0 the minimum. P5 (bca4074a632c) PASS — statically, every read of the attempts-log setting is `args.attempts_log` (argv only; nothing assigns it, no environment lookup feeds it, no other module references it), and the flag's help text now states that trust level next to it. P10 (c5f02551d077) PASS with the directed label fix below — a solo verification round is labelled in every outcome, and a chain containing one still fails `rounds_two_families`. P11 (0e57186e8be8) PASS — `agent:x:sh -c 'echo a:b'` parses with the command intact, and the built seat executes it. P12/P13 (1aec997aaec4 + 0ad4ed7db98e) PASS — the doc's property test over all 13,692 permutations of subsets of the mixed spec list (a preset, agent case variants, agent suffix collisions, a custom API spec): every combination either raises `ProviderError` loudly or builds exactly one seat per spec with case-insensitively unique names; no silent merge anywhere in the space. P14 (2242edbba9c9) PASS — providers' module scope provides the `os`/`signal` objects `_kill_tree` uses, and the module imports clean under warnings-as-errors.
- **P9 (d93089253022) — the matrix confirms the overmatch refutation, and surfaces one thing §3 did not predict**: patterns `app/` and `app` match exactly the directory's children (the sibling `app/users2.py` and the prefixes `app2/`, `application/` never match), and `app/users` rejects its prefix traps — but the spelling `./app` matches NOTHING, not even the directory's own children: the leading `./` is not normalized away, so a manifest author writing it gets an inert pattern. The direction is fail-safe (an inert pattern marks fewer fixtures; it can never hide a product finding), but it is silent. Pinned by a clearly-named characterization test; per the adopted rule this goes back to the owner WITH the §3 ruling rather than being silently fixed here.
- **The shared `_is_within` helper (P6/P8 — eae8137a6db3 + 3cecf66f6ce5; the fix §3 directs at minor severity)**: both containment call sites (the fixture-manifest loader and the precedent loader, both in `cli.py`) now share one helper that realpaths both sides, compares with `os.path.commonpath`, and returns `False` on `ValueError` instead of propagating it — a containment question that cannot be evaluated fails closed. Tests pin the monkeypatched-`ValueError` path (helper `False`; the loaders raise their own "resolves outside" error), the `ntpath` different-drives `ValueError` that is the mechanism behind the findings, and unchanged within/outside behaviour including the prefix-sibling case.
- **Solo-panel label in verification records (P10's directed fix, c5f02551d077)**: `run_verification` appends the standalone "solo panel — no independent review" reason whenever the verification panel has one seat or fewer. Previously only a clean solo PASS carried the wording (embedded in its pass sentence), so a solo round ending blocked or inconclusive read like a panel verdict. The review path's label is unchanged, and eligibility still fails a solo round at `verify_chain`'s `rounds_two_families` check.
- **Internal review of this diff (verdict as received — no PASS is claimed)**: **BLOCKED**, 88 standing findings (20 blocker, 40 major, 28 minor), not degraded, coverage complete, the record's own test run green (299 tests); 29 further findings were withdrawn in the re-ground pass. Gemini quota-failed on every batch (not retried) and the OpenAI fallback served correctness, with NVIDIA on operations. Composition, stated plainly: the release commit also newly tracked the prior rounds' record files (review-v9c…v15, review-v095-fix, `gate-attempts.jsonl`, ~13.6k lines of historical evidence), and 68 of the 88 findings target those artifacts — including findings about code as preserved inside the old records; the 20 findings on source files sit overwhelmingly in pre-existing code outside this release's hunks. 6 findings were refuted cross-family and are recorded as **disputed, not adjudicated** (per the adopted §2 rule): two of them re-raise the P6/P8 `commonpath` claims against the pre-fix lines preserved in the historical records. The verdict stands as received; disposition of its findings belongs to the owner's ruling process and later steps, not to this release.
- Suite: 299 tests (23 new).

## 0.9.5 — 2026-11-04
The review-v15 machinery release: the three build items the Phase 3 closing run's successor report (`2026-11-04-codereview-v15-closing-run.md`) named as the bars to any further closing run. No closing attempt ships in this release — the re-run also waits on the owner's rulings on the 14 disputed majors, which this release does not touch, waive, or adjudicate.
- **Oversized diff sections are sub-split, never truncated (bar 1)**: `_batch_sections_detailed` cut a section larger than the batch budget down to size (`text[:max_chars]`), which is why review-v15's round 1 degraded with incomplete coverage — `src/codereview/core.py`'s cumulative section is 94,494 chars against the 80,000 budget, while file/lens omissions were 0. A new `_split_section` now sub-splits an oversized section at diff-hunk boundaries, then at line boundaries inside a single oversized hunk, then by character-splitting a single over-long line; every piece repeats the section head (and the hunk header on line-split pieces) so a reviewer always knows which file and hunk a piece belongs to, hunk bodies are never dropped or reordered, and the coverage ledger names the file in every batch that carries a piece of it. The batching flag (record field `truncated`, kept for compatibility) now means batching *incomplete* — content that could not be placed within the budget at all (only reachable when the budget cannot hold even a minimally framed slice) — and the run still degrades loudly in that case; the gate and coverage reason strings say so in those words. Regression tests cover a multi-hunk section landing completely, the v15 shape at its real numbers (~94.5k section, 80k budget), line-boundary and character splits, the unplaceable edge, and a full `run_review` whose coverage stays complete over an oversized section; the two tests that pinned the old truncate-and-flag behaviour are updated to the new semantics.
- **Verification rounds honor the fallback seat map (bar 2)**: in review-v15-verify1 the panel was quota-failed Gemini + NVIDIA only — the runner supplies a fallback map (`fallbacks_override`, OpenAI behind the correctness lens) but the CLI's verify branch never forwarded it and `run_verification` did not accept one, so the one OpenAI-raised blocker could not be finder-confirmed and came back unjudged. `run_verification` now takes the same lens → seat `fallbacks` map as `run_review`: when a primary fails, the fallback configured for the lens that seat would serve in a review round (the `_reviewer_tasks` assignment) runs the verification job under the same bounded-substitution contract as a review round — reason recorded in the gate reasons, only the job budget's remaining attempts spent, the report carrying the serving seat as `provider` with `fallback_for` and `primary_error`, new findings attributed to the serving seat — and the CLI forwards the map in verify mode, so the runner's verification path is wired end to end. Review-mode behaviour is unchanged, as are the loop and PR paths (they pass no map). Regression tests pin the deadlock's resolution (quota-failed primary → fallback serves → finder confirmation completes, gate PASS), the no-map behaviour (finding stays unjudged, INCONCLUSIVE), a failing fallback recorded on the primary's report, and the CLI seam the runner actually uses.
- **Chain verification normalizes abbreviated SHAs (bar 3)**: `record-verify --chain` compared range endpoints to `head` fields as raw strings; records store full SHAs in `head` while the v15 ranges were supplied abbreviated (`e3fc6a8` vs `e3fc6a8c12ba…`, the same commit), so `ranges_contiguous` reported a gap in a contiguous chain. Both sides are now resolved to full SHAs against the repo (cached per run) before comparison; an endpoint that does not resolve compares as its raw string, so a bad ref still fails honestly, and a genuinely gapped chain — abbreviated or not — still fails. Regression tests verify an abbreviated chain identically to its full-SHA form and keep an abbreviated gap failing.
- **Internal review of this diff (verdict as received — no PASS is claimed)**: **INCONCLUSIVE**, 0 standing findings, not degraded, coverage complete, the record's own test run green (276 tests). Gemini quota-failed (not retried) and the OpenAI fallback served correctness — the fallback machinery working in its new verify-adjacent shape — with NVIDIA on operations. Two majors were refuted cross-family and routed to the human gate as disputed; the builder adjudicates both as false positives on code evidence: (1) "an unplaceable oversized piece is appended to a fresh batch without any size guard" describes the designed loud path, not a defect — the only alternative to carrying unplaceable content whole in its own batch is dropping it, and the batching flags the case (`incomplete` → coverage incomplete → run degraded, stated in the gate reasons; pinned by `test_unplaceable_budget_is_loud_and_keeps_content`); (2) "the verification fallback lens mapping is wrong for the second seat" hypothesizes a panel with more than two lenses, but `LENSES` is a two-entry constant (correctness, operations) and the mapping copies `_reviewer_tasks`' assignment verbatim — the same assignment the review path itself uses, which is precisely the parity bar 2 set.
- Suite: 276 tests (12 new).

## 0.9.4 — 2026-11-04
The review-v15 adjudication release — the Phase 3 closing run's round 1 and its verification, shipped with verdicts exactly as received. Round 1 (attempt 11, span `3013656..e3fc6a8`, record `review-v15/codereview-20261104-224759.json`) came back **BLOCKED and degraded**, so this release changes no product code: all five round-1 blockers were rebutted on executable evidence, now pinned as characterization tests in `tests/test_v094_probes.py` (suite 264/264) — the review fallback construction does forward `agent_timeout` (cli.py:698-699); every provider call path carries a timeout (`_post_json`'s `DEFAULT_TIMEOUT = 240` is the only opener site); `_call_with_retry` is hard-bounded per class and per job; `_classify_error`'s whole-token matching is the v0.9.3 fix itself; and `_kill_tree` cannot flip a successful agent run (it never raises on a dead group, and the return code is captured first). The new machinery did its job in the open: 9 findings withdrawn by their own seats in the re-ground pass, 5 standing findings auto-linked under precedent, 44 fixture findings classified. Two things keep the record ineligible, stated plainly: **coverage was incomplete** — `src/codereview/core.py`'s cumulative diff section is 94,494 chars, over the 80,000-char batch budget, and `_batch_sections_detailed` truncates an oversized section instead of sub-splitting it (0 file/lens omissions; the sub-split fix is the next round's first build item, and it needs a fresh round 1); and **14 majors stand disputed** — refuted cross-family with valid quotes, therefore out of the blocking set but not cleared, awaiting the owner's human-gate ruling. Full dispositions: `review-v15-dispositions.md`. The announcement hold stays on.

## 0.9.3 — 2026-11-04
The Phase 2 release of the owner's v14-hold solution — the release that stops the clean-gate treadmill instead of feeding it another round. Phase 0 of that plan reconstructed review-v14's coverage from the record and **ruled truncation out**: all 430,878 post-redaction patch chars reached both lenses (0 omitted hunks), and the two findings that contradicted verified facts cited text that WAS in the batches — the failure was reviewer quality on large batches (a seat counted the corpus's 9 holdout cases twice: 36 + 9 = "45"), not missing text. So this release's centre of gravity is grounding and confirmation, with coverage kept as the record's own proof. It also carries the Phase 1 adjudication fixes (commit `5119998`, previously unreleased): 2 real defects fixed, 13 findings rebutted with executable evidence — full table in `review-v14-dispositions.md`, coverage reconstruction in `review-v14/coverage.md`. The owner adopted all three of the solution's reserved decisions on 2026-11-04 — Form B, record-and-attest, content-addressed precedent — and all three are built here. No closing attempt ships in this release; Phase 3 runs it.
- **Evidence-grounded findings with an automatic re-ground pass (solution §2b)**: the review prompt now requires an `evidence_quote` copied exactly from the diff, and every model finding's quote is validated deterministically against the batch text its reviewer actually received. A failing finding is never dropped: the raising seat (or another family's) is shown the exact file section and must confirm with a valid quote or withdraw. Confirmed → the finding stands, marked `reground_confirmed` with the validated quote; withdrawn → preserved in `withdrawn_findings` with the seat's reason; unresolved → the finding stays visible and a would-be PASS becomes INCONCLUSIVE for a human. Deterministic findings are validated against the material they cite (or marked not-applicable, e.g. test-output evidence).
- **Cross-family confirmation for blockers (solution §2c)**: a blocker/major raised by one vendor family is put to a different family's seat that served the run, with the cited file's section as the region. Confirm → it stands (`cross_family: confirmed`). Refute counts only with a quote that validates against the region → the finding becomes **disputed**: out of the blocking set, listed in `disputed_findings`, and the gate may not auto-PASS (INCONCLUSIVE — the human gate decides; it is neither auto-cleared nor silently blocking). A refutation without a valid quote, a failed call, or no second family served leaves the finding standing, marked `unresolved`/`unavailable`.
- **Coverage accounting carried by the record (solution §2a)**: every review record now carries per-file, per-lens batch coverage derived from the actual batching (each reviewer report names its batch). A file/lens omission — or a truncated section — marks the run degraded at review time and is stated in the gate reasons. `record-verify` gains `coverage_complete`: a record WITH coverage data is held to it; a record without (pre-0.9.3) reports the check not-applicable rather than failing retroactively.
- **Form B chain verification (solution §2d)**: `codereview record-verify --chain <round-1> <verify> [...]` verifies a round-structured record as one object — ranges contiguous base→HEAD (hash-checked, no gaps), every round non-degraded with two families, round-1 lens coverage and complete coverage, every round-1 blocker/major dispositioned on the record (present in a verification round's `cleared` list — an all-`invalid` clearance is the ruled rebuttal), final gate PASS, tests passing, final head current (later commits may touch only the chain's record directories). The adopted convergence budget (≤3 verification rounds, non-increasing new-blocker counts) is emitted as `[WARN]` lines: a process flag for the owner, distinctly NOT an eligibility failure. Verification records now also carry `test_results`, `range`/`head` (via `record_extra`), and the `private` attestation, so chains can be built from real CLI runs.
- **Tier attestation — record-and-attest (owner decision (a), settling v13 finding [4])**: run records carry the run's `private` declaration; seats already record their tier. `record-verify` gains `tier_policy`, which fails ONLY the adopted conjunction — `private=true` AND a successful (ok-status) seat on a free tier. A public run attests `private=false` and passes with free seats; a record with no declaration reports not-applicable. The run-time refusal in `--private` (free seats refused before the run) is unchanged.
- **Content-addressed rebuttal precedent (solution §2e, owner decision (b))**: a new store, `precedents.json` (schema `codereview.precedents/1`, passed with `--precedents`), keys finding fingerprint + cited path → the cited file's git blob at disposition time, the disposition reference, and the rounds it was seen in. During record assembly a matching finding whose cited file's blob at HEAD is unchanged is classified `standing` — listed in `standing_findings` with its repeat count and disposition link, non-blocking; a changed blob means fresh adjudication, so a precedent can never hide new code. `record-verify` recomputes the store hash and every link (entry exists, blobs equal at the recorded head) exactly as it validates fixture scope. The store is seeded with the five guard-minor dispositions sustained across review-v11..v14 (the POSIX platform-guard repeats); every seeded file is unchanged since its single touching commit, so HEAD blobs are the disposition blobs (basis recorded per entry). `core.upsert_precedent` maintains entries programmatically.
- **Fixture expected counts (solution §2f)**: a manifest entry may declare `expected_finding_count`; findings on that path beyond the count are NOT classified as expected — they remain product findings in the record, the excess is noted in the gate reasons and in `fixture_scope.excess`, and record-verify's recompute stays consistent (the count classifies, the excess never disappears). The shipped manifest declares no counts (policy-v1 behaviour unchanged).
- **Phase 1 fixes riding this release (review-v14 adjudication)**: `_classify_error` matched HTTP status codes as bare substrings, so a 503 body mentioning "4030 tokens" (or a request id "req_4014") classified as auth and a transient failure was denied its retries — status codes now match as whole tokens, and the typed provider quota codes (`resource_exhausted`, `insufficient_quota`) decide the quota class directly. And bench `--force` now refuses to swap in a results file when any case in the forced run came back degraded: `run_review` absorbs provider failures into degraded records rather than raising, so a forced run during an outage silently replaced good results with 27/27 degraded ones (probe-verified); the refusal keeps the previous file byte-intact and exits cleanly with the reason.
- **Housekeeping (solution §2f)**: `codereview doctor` output now states the live-probe rule in the result itself — a seat counts as wired only after a live probe in the runner's exact review call shape (the probe prompt already uses the real review shape; verified, no residual toy probe in any path). `gate-attempts.md` already carries the attempt-6, review-v11 and attempt-10 rows (completed in the v0.9.0/v0.9.2/Phase-1 rounds).
- **Internal review of this diff (two rounds, verdicts as received — no PASS is claimed)**: round 1 returned **INCONCLUSIVE** under the new machinery itself — 0 standing blockers, coverage complete, not degraded; 13 findings were withdrawn by their own seats in the live re-ground pass (the §2b mechanism working on its own release), and 4 majors were refuted cross-family and adjudicated at the human gate as false positives or by-design, each verified against the code (the precedent loader canonicalizes `repo_abs` exactly like the fixture loader; the missing-blob scenario is guarded in `apply_precedents` and at load; deterministic grounding is validated in `run_review`; the chain's test-results requirement is the documented Form B design). Of its 4 minors, one (direct unit coverage for `_batch_sections_detailed`) was fixed in-release and three rebutted (two are the deterministic guard-text hits on quoted text; one asked to verify a constant that is defined and test-covered). Round 2, on the updated diff, returned **BLOCKED** on two majors claiming the new logic "lacks unit tests" — both rebutted with the test classes in the same diff (the claim is a per-batch blindness artifact: the seat judging a batch cannot see the test file in another batch, while the record's own test run executed all 253) — plus 4 more disputes, all sustained on schema/code evidence, and 5 minors rebutted. No real defect was found in either round; the rounds are recorded here because the saga's rule is that verdicts are reported as received.
- Suite: 253 tests (37 new).

## 0.9.2 — 2026-11-04
The review-v13 adjudication release. The v0.9.1 closing attempt (review-v13) blocked on 6 majors + 5 minors + 1 nit; every one was adjudicated against the code — 1 fixed as a real defect, 4 rebutted as false positives with executable evidence (one of them, the "unused import" nit, refuted by the very file it cited), 1 left as an explicitly owner-reserved decision with a decision memo (no builder accept, no silent enforcement change), and the 5 minors recorded as standing repeats of a rebuttal first sustained in v11. The full disposition table, with finding IDs and evidence, is `review-v13-dispositions.md`; the governing issue report is `~/workspace/issue-reports/2026-11-04-codereview-v13-gate-findings.md` (outside the repo).
- **Explicit agent timeouts are honored or refused — never silently swapped (real, v13 [5])**: `build_provider` built agent seats with `timeout=agent_timeout or AGENT_TIMEOUT`, so a library caller's explicit `agent_timeout=0` became the 900-second default without a word (proven by probe: 0 → 900 captured; a negative value passed through to fail late and confusingly). The CLI boundary has rejected non-positive `--timeout` since 0.9.1, but the library seam had not. `build_provider` now passes `AGENT_TIMEOUT` only when `agent_timeout is None`, and `command_agent` — its sole construction path — refuses a non-positive timeout at construction with a `ProviderError`. Regression tests pin all four quadrants (None / zero / negative / positive) at the singular, plural, and direct seams (`tests/test_v092_fixes.py::AgentTimeoutSeamTests`).
- **Characterization tests pin two rebutted invariants** so they cannot rot silently: bench resume after a config rename (v13 [2] — the config name is inside `_config_sha`'s hashed identity, so foreign records are dropped as stale before dedup; the test drives the strongest form, old-name records planted in the renamed config's own results file) and fixture sibling-prefix rejection (v13 [3] — every pattern in the shipped `fixtures-manifest.json` is swept against sibling mutations; matching stays boundary-aware in both pattern branches).
- **Owner-reserved, deliberately untouched**: whether `record-verify` should enforce the free-tier policy (v13 [4]) is a decision about what a clean record claims, not a code defect this round may settle; `review-v13-dispositions.md` carries the decision memo (current policy mechanics, the missing `private` declaration in the record schema, three options, a recommendation). The rebuttal-precedent mechanism proposed in `review-v12-dispositions.md` likewise remains the owner's decision — the five guard minors in v13 are its standing repeats.
- Suite: 202 tests (9 new).

## 0.9.1 — 2026-11-04
The review-v12 adjudication release. The v0.9.0 closing attempt (review-v12) blocked on 10 product findings + 6 minors; every one was adjudicated against the code — 3 fixed as real, 6 rebutted as false positives with executable evidence, 1 recorded as a repeat of an already-sustained rebuttal, and 1 code-reading correction to the round's own triage (the doctor half of the "confirmed" timeout pair already forwarded at HEAD; the enumeration test now proves every path instead of trusting the claim either way). The full disposition table, with finding IDs and evidence, is `review-v12-dispositions.md`; the governing issue report is `~/workspace/issue-reports/2026-11-04-codereview-v12-gate-findings.md` (outside the repo).
- **Review runs can configure the agent timeout, forwarded to primaries AND fallbacks (real, v12 [3])**: the review command had no `--timeout` option at all, and its fallback construction omitted the forwarding that doctor/intake already had — an asymmetry waiting to bite. `codereview --timeout N` now exists and reaches both constructions in `main()`, exactly mirroring `doctor --timeout`. The doctor fallback path (v12 [4]) already forwarded at HEAD — git history shows it landed with v0.9.0 and its evidence quote showed the forwarding lines; what was missing was a test exercising the fallback branch, which the enumeration suite below now supplies for every path.
- **Enumeration test over every seat-construction path (closure criterion)**: `tests/test_v091_fixes.py` walks the AST of `cli.py`, `bench.py`, and `providers.py` and accounts for EVERY `build_providers`/`build_solvers` call site: each either forwards `agent_timeout` or belongs to a command that exposes no timeout option (loop / workflow / pr / bench-config), with a companion assertion that an allowlisted command still has no `--timeout` flag — so adding a timeout option anywhere without wiring its forwarding fails the suite loudly, as does adding a new construction path without accounting for it. Functional spy tests drive review and doctor with `--timeout 7` and assert primaries and fallbacks both receive it.
- **Bench `--force` replaces stored records instead of duplicating them (real, v12 [1])**: a forced rerun skipped the staleness filter but still appended, so each forced run stacked a second set of records for the same (config, case) into the results file. Replacements now stream to a sibling temp file and are swapped in atomically when the config's run completes, so a mid-run failure also leaves the previous results intact (hardening from this release's own internal review round); regression tests cover both the record count and the failure case.
- **Non-positive `--timeout` values are rejected at the CLI boundary** (internal review of this fix diff): review, doctor, and intake validate the flag before any seat is built — a zero or negative value would otherwise reach the agent subprocess and surface as a confusing seat error. Regression tests cover all three commands.
- **Fixture classification hardened at the source (v12 [8])**: `_fixture_inner_paths` now subtracts the patch's top-level file names itself, instead of relying on each caller to remember the check. A product file can no longer be classified as a fixture inner path even by a future caller that forgets the guard; the callers' own checks remain as defence in depth. Unit tests cover the colliding and non-colliding shapes.
- Suite: 193 tests (18 new).

## 0.9.0 — 2026-11-04
The review-v11 adjudication release, built to the owner's clean-gate solution. The v0.8.0 span review (the first attempt where the OpenAI fallback served the correctness lens end-to-end) blocked with 40 findings; every one was adjudicated against the code — 26 were the benchmark's own fixture data, 4 were real, 9 were false positives, 1 minor was a docs gap. The full disposition table, with finding IDs and evidence, is `review-v11-dispositions.md`.
- **Fixture scope as a versioned, machine-checked manifest (solution §3)**: `fixtures-manifest.json` (policy v1) enumerates every fixture path — all 36 corpus cases and the three scripted-seat response files — with the reason each is intentionally vulnerable and its expected finding categories. A release-record review passes `--fixture-manifest`: the patch is still reviewed **in full** (nothing is dropped), but findings belonging to declared fixture data are classified in the record as `fixture_findings` — evidence and counts preserved — and do not block the gate. The record carries the manifest path, its content hash, the policy version, and the classified paths; `record-verify` recomputes all of it against the manifest committed at the recorded head and FAILS on a missing, stale, or mismatched manifest, on classified paths that differ from the manifest, or on a fixture finding the manifest does not cover. Findings reported under a fixture's *inner* paths (a case diff's own little file tree) are classified too — unless the same path is also a real file in the change, in which case the finding stays blocking. Ordinary reviews without a declared scope scan fixtures exactly as before.
- **Doctor probes use the exact review request shape (solution §4)**: the preflight probe is now the real review prompt over a trivial diff. The old toy probe ("reply OK") had produced a documented false-negative for a healthy JSON-mode seat, whose provider rejects non-review-shaped requests. `codereview doctor` also probes **fallback seats** (a fallback counts as healthy coverage only after this live probe; `--fallback lens=spec`, or the runner's configured fallback) and forwards `--timeout` to provider construction like review and intake do. Per-seat error classes still distinguish quota/transient from missing credentials (auth).
- **Bounded primary+fallback attempts (solution §4)**: one reviewer job has a hard budget of 6 provider calls; the fallback job is handed only the remaining budget after the primary's attempts, and if the budget is already exhausted the fallback is not attempted — with the reason recorded in the gate reasons. A fallback-served report's attempt count is now the primary+fallback total (it previously recorded only the fallback's, understating run cost — a real v11 finding).
- **Bench resume no longer trusts stale records (real)**: stored result records are re-validated on resume — the recorded patch hash must match the case's current diff and the recorded config hash must match the current config; stale records are dropped and the results file rewritten. `bench report` likewise drops hash-mismatched records and counts them (`stale_records_dropped`) instead of scoring findings gathered against a different change. Records now carry `config_sha256`.
- **Seat-name collision checks are case-canonical (real)**: the cross-kind check (agent seat vs API seat) compared names case-sensitively on the custom-spec branch, so a case variant could slip an agent seat past an API seat of the same name. All pre-pass comparisons, including suffix bookkeeping, now use the lowercased canonical name.
- **Default seat metadata reads the seat kind, not the name (real)**: resolved agent seat names are bare and suffixed (bot, bot-2), and one named like a preset inherited the preset's vendor family. `build_providers` now tags agent callables with their kind; `_default_seat_meta` reads the tag, so agent seats record family `agent` under every name.
- Docs: the bench growth path names an owner and a timeline; the ROADMAP's fixture item is updated (manifest classification shipped; in-code suppression comments remain open).
- Suite: 175 tests (40 new).

## 0.8.0 — 2026-11-04
Epic A — the benchmark harness and corpus v0 (the revised plan's Week-1 epic; it blocks everything else, so it ships before any new surface):
- **`codereview bench run|report`**: run named panel configurations over a labelled corpus and score them against ground truth. `bench run --config X` (repeatable; configs are small JSON files naming provider specs and/or seats) appends per-case records to `bench-out/<config>.jsonl` and resumes — recorded cases are skipped unless `--force`. `bench report` prints Markdown and can write MD+JSON; `--max-escaped-rate R` turns it into a CI regression gate.
- **Metrics, defined in code and in `bench/README.md`**: recall, precision, clean-case false-positive rate, cost per verdict, p50/p95 latency, and the headline **escaped-defect rate** — defects no finding blocked on (unseen, or reported only as minor/nit, so the default gate would have shipped them). Matching is file + location (line within 3, or title-token overlap when lines are far/missing); one-to-one, worst severity first.
- **Corpus v0**: 36 cases (27 public / 9 holdout), 29 defect cases with 31 ground-truth defects + 7 clean controls — authored defect injections (secrets, SQL/shell injection, auth removal and bypass, dollars-vs-cents and partial-refund payments, races, swallowed errors, traversal, XSS) plus cases converted from this repo's own stored run artifacts (the demo health-checker change and its verified fix). Loader validates every case and refuses a manifest that disagrees with the directories on disk. Growth path to 50–100 documented in `bench/README.md`.
- **Holdout discipline (A5)**: `bench report --public` drops holdout records before scoring — no holdout id, row, or number can appear in public output; a regression test asserts it.
- **Scripted replay seats** for deterministic, zero-call CI runs (`oracle` replays ground truth, `blind` reports nothing, `noisy` complains about everything). Their scores validate the harness, never a model. On corpus v0 the scripted runs already surface two honest facts: the deterministic layer alone accounts for recall 0.452 (13 of 31 defects), and cross-layer duplicate findings under dissimilar titles cost precision — recorded in `bench/README.md`, not tuned away.
- Suite: 136 tests (15 new).

## 0.7.3 — 2026-11-04
The §4 hardening from the owner's clean-record solution — written after five attempts at a two-reviewer release record for the v0.7.1+v0.7.2 span failed on capacity and credentials, never on findings:
- **Preflight** (§4.1): `codereview doctor` probes every configured seat with one minimal call and reports per-seat health as JSON (ok / error class / message). A scheduler aborts on a dead seat before a doomed run creates a record; a missing key surfaces as class `auth`, naming the actual problem.
- **Error-class-aware retries** (§4.2): failures classify as quota / rate_limit / transient / auth / provider (typed, via v0.7.1's `retryable` flag, which wins over string matching) / unknown. Daily-quota and auth failures are never retried inside a run; per-minute 429s and 5xx/overload/timeouts get bounded backoff (3 tries). Attempts and error classes are recorded on every reviewer report — retries are visible, never silent. (Suite note: failing-seat tests now exercise real short backoffs; the suite takes ~25s.)
- **Fallback seat per lens** (§4.3): `--fallback lens=provider-spec` (or a runner-supplied mapping) serves a lens when its primary seat fails after retries. The report records `fallback_for` + the primary's error, the gate reasons name the substitution, and Markdown prints it. A fallback cannot launder a panel: record verification (below) still requires two distinct vendor families.
- **Machine-checked clean record** (§4.4): `codereview record-verify <dir> [--repo .]` returns eligible / not-eligible with per-check reasons: gate PASS, not degraded, tests passed, every lens served, ≥2 distinct known vendor families, the recorded range's patch hash recomputes identically, and no commits after the recorded head except ones filing the record directory itself. Records now carry `range` + `head` when produced from `--range`; pre-0.7.3 records fail the currency checks with the reason stated.
- **Seat metadata + free-tier policy** (§4.6): reviewer reports carry `family` and `tier` per seat (`--seat-meta name:family[:tier]`; presets get family defaults, tier stays "unknown" unless tagged). `--private` refuses seats explicitly tagged tier `free` — free tiers may use submitted content to improve the provider's products, so they do not review private code.
- **Attempt ledger** (§4.5): `--attempts-log FILE` appends one JSON line per run (mode, gate, degraded, range, seats with attempts/error classes/fallback use). This repo's own attempt history for the span is summarized in `gate-attempts.md`.
- Internal runner: seats are tagged (Gemini google/free, NVIDIA nvidia/free), and an OpenAI seat (openai/paid) rides as the correctness fallback whenever its connector credential is registered (owner decision 2026-11-04). DeepSeek remains editorial-box-only and is never seated.
- Suite: 120 tests (24 new).

## 0.7.2 — 2026-11-04
External review of v0.7.1 (APPROVE the code; HOLD the announcement for a healthy two-reviewer gate record). Its two required items and all five recommended items are in:
- **Unique agent names, always** (required, §3.1): final seat names are assigned in a pre-pass over all specs; suffixes bump the trailing number (bot → bot-2 → bot-3) until unique, so a literal `bot-2` seat can no longer merge with the second `bot` seat into a pool that never runs. All three seats in the reviewer's reproduction now run.
- **Process group killed on every exit** (required, §3.2): the seat's group is killed after a normal exit too, not only on timeout — background children an agent spawns die with their seat.
- **First-round lens coverage** (§3.4): a review PASS now requires every configured lens to have had a successful reviewer; a partially blind panel is INCONCLUSIVE, matching the verification standard. (Two older tests encoding the degraded-PASS behavior were updated to the new rule, with citations.)
- **Write-side output cap** (§3.3): POSIX seats run under RLIMIT_FSIZE (8 MB per file); a runaway agent dies with SIGXFSZ and the seat reports the limit instead of filling the disk.
- **Private-HOME seat option** (§3.5): `agent:<name>[home=private]:<command>` runs the seat with HOME set to its scratch directory, for agents that need no login state. Regression tests document the tension honestly: the default seat CAN read a planted key under HOME (subscription agents keep login state there); the private-HOME seat cannot. An obeying-stub injection test locks the scratch-cwd guarantee.
- **Wording and labels** (§2, §3.6): the verification INCONCLUSIVE reason now says the way forward (fresh review with the finder present, or a human waiver); solo panels are labelled "solo panel — no independent review" in both review and verification pass reasons.
- Gate record: tonight's runs are again degraded by the Gemini free-tier quota (the code is unchanged in the panel's eyes — NVIDIA clean); the publishable two-reviewer record for the 0.7.0→0.7.2 span is scheduled for ~03:20 ET, after the quota reset. Suite: 96 tests (12 new).

## 0.7.1 — 2026-11-04
External review of v0.7.0 (APPROVE WITH REQUIRED FIXES): every required item verified against the code and fixed.
- **Agent-seat environment is allow-listed** (finding 1): seats inherit only PATH/HOME/locale/proxy basics plus `CODEREVIEW_PROMPT`; provider API keys and tokens stay out unless the operator opts names in via `CODEREVIEW_AGENT_ENV`. Sentinel-key regression tests.
- **Verification integrity** (finding 2): a PASS now requires a quorum of ≥2 successful reviewers when ≥2 are configured, and each prior blocker must be confirmed by the seat that raised it (deterministic findings clear only when the pattern no longer fires). Unconfirmed blockers are INCONCLUSIVE ("unjudged"), never a one-reviewer "consensus"; pass reasons state the real counts, and Markdown reports carry a ⚠ DEGRADED marker with the reviewer tally whenever a panel is degraded. (The shipped v0.7.0 verification record — PASS on one surviving reviewer — would be INCONCLUSIVE under these rules; a regression test encodes exactly that shape.) One deliberate refinement: a reviewer answering "unclear" still keeps the block (BLOCKED), as before — INCONCLUSIVE is reserved for panel-side inability to judge.
- **Agent-seat isolation** (finding 3): seats run in a fresh scratch directory containing only the prompt file — never the repo working tree — and the README now states the boundary plainly: redaction covers the prompt CodeReview sends, not files a tool-enabled agent chooses to read; seat only agents you trust with their own permissions. The Claude Code example wrapper disables all built-in tools (`--tools ""`).
- **Seat namespaces** (finding 4): an agent seat and an API seat sharing a name is now a loud configuration error in either spec order, instead of a silent pool merge.
- **Lifetime** (findings 5, 6.1): agent seats run in their own process group; a timeout kills the whole tree. Solver seats default to the intake deadline (300s, or `--timeout`), so a hung agent can no longer keep the CLI alive past its run. Output is captured to files and capped at 1 MB (verdict tail kept). Agent-seat errors carry a typed `retryable=False`, so stderr text can no longer trigger account rotation (6.3). Noisy agent output (banners, fences) is covered by a parsing regression test (6.4).
- Docs hygiene (6.7, 6.8): REVIEW-NOTES pointers corrected (the v0.1.0 `review-evidence/` package is not in this archive; gate records live in the `review-v*` folders); the 0.7.0 entry below is final. Suite: 84 tests (15 new).

## 0.7.0 — 2026-11-04
Direction set by the revised plan adopted 2026-11-04: one promise — a verifiable verdict with a public record — proven by a public benchmark; launch scope narrows to CLI + Action + benchmark + run pages (console/iOS frozen as internal surfaces, hosted tier and editor extensions deferred to demonstrated demand).
- **Agent seats** (`--provider "agent:<name>:<command>"`): any local agent CLI can sit on the reviewer panel or as an intake solver — Claude Code, Codex, a Grok bot, Gemini CLI, or a wrapper script — riding on the agent subscription the user already has; no vendor API key required. The prompt is delivered as a file (`$CODEREVIEW_PROMPT`) and on stdin; the agent's stdout is the verdict. The command line is shlex-split and run **without a shell** (metacharacters are literal; pipes/redirects belong in a wrapper script), and same-named agent specs stay distinct seats (`name`, `name-2`, ...) since each runs a different command. Non-zero exit, timeout (900s), or empty output degrades the seat honestly, like any provider failure. The command is operator-supplied (the `--builder-cmd` trust level), never taken from a repo or diff. Example wrapper: `examples/agent-seat-claude.sh`. Gate record: review-v7 BLOCKED (shell-exec major + same-name seat collapse, both real) → fixed → verification. Suite: 69 tests (13 new).

## 0.6.0 — 2026-11-03
- **Distribution name: `codereview-ai`** (owner decision, 2026-11-03). The PyPI names `codereview` and `codereview-cli` are both taken by unrelated projects; `codereview-ai` was verified free and is now the package's distribution name. The installed command remains `codereview`. Publishing itself waits on the GitHub reinstatement, per the internal-first plan.
- **Intake mode** (`codereview intake <issue-report.md> [--context FILE ...] [--repo DIR]`): the front half of the workflow. Until now every entry point started from a code change that already existed; intake starts from the problem. Solver models read the issue report (plus optional context files and the repo's file listing) and each produce a solution plan in a fixed, executable shape: diagnosis steps in order, ranked hypotheses each with the test that settles it, a numbered fix plan, prevention, risks and rollback, and closure criteria. The first configured solver that answers becomes `solution.md`; other solvers' plans are kept as alternates, and `intake.json` records the report's sha256, per-solver outcomes, and every truncation. Exit 0 = a plan was produced, 2 = every solver failed.
- **Solver seats** (`providers.build_solvers`): the same presets, custom specs, and account pools as the reviewers, but answering in plain text — a solver-persona system prompt and, for Gemini, no JSON response mode (the reviewer callables are byte-for-byte unchanged in behaviour).
- Intake never writes code and never gates: the builder implements `solution.md` and the existing review loop gates the change. Report and context pass through the same secret redaction as diffs and are size-capped, with truncations disclosed inside the prompt itself. Suite: 56 tests (12 new). Self-review: the intake diff went through the loop — round 1 BLOCKED (6 findings: a per-solver timeout and a worker cap were added, the redaction test's fixture was rebuilt from fragments, and two findings were rebutted with code evidence locked in by new wire-level tests), verification round 2 PASS with all prior blockers cleared by reviewer consensus.

## 0.5.0 — 2026-11-03
- **Renamed: ReviewLoop is now CodeReview.** Package `codereview`, CLI `codereview`, builder env contract `CODEREVIEW_*`, GitHub commit-status context `codereview`, approval commits authored as CodeReview. Backwards compatibility is kept for one transition: a `reviewloop` import shim and CLI alias ship in the package, builders receive both `CODEREVIEW_*` and legacy `REVIEWLOOP_*` variables, and `$REVIEWLOOP_PROVIDERS` is still honoured. No behaviour changes. Note: the PyPI distribution name `codereview` is already taken by an unrelated project (a desktop diff viewer), so a future PyPI release will need a distinct distribution name; the GitHub repository name is unaffected.

## 0.4.2 — 2026-11-03
External Review 3 — verdict was Approve; its one Minor is fixed:
- **Approval commits are assembled in a temporary Git index.** The engine now builds the commit with `GIT_INDEX_FILE` pointed at a throwaway index (read-tree the step base → add the working tree → verify the staged diff is byte-identical to the approved diff → write-tree → commit-tree → HEAD moved by an update-ref guarded on the base). The v0.4.1 recovery path ran `git reset -q -- .` on a staged-diff mismatch, which reset the user's whole index and destroyed pre-staged state belonging to a resumed step. Now a refusal touches nothing: the temporary index is discarded and the user's index is exactly as it was. On success the real index is synced to the new HEAD — the state a normal commit leaves behind.
- Regression test: a resumed step with pre-staged work that hits a forced staged mismatch keeps its staged entries after the refusal (`test_mismatch_refusal_preserves_staged_index`); the exact-commit test now also asserts a clean post-commit index. Suite: 44 tests. Full response: `review-3-response-2026-11-03.md`.

## 0.4.1 — 2026-11-03
External Review 2 — one Major, verified real by reproduction, fixed:
- **Workflow steps are isolated from the user's working tree.** A step starting fresh now requires a clean tree (staged, unstaged, and untracked changes all count; the workflow output directory is excepted): the engine stops with `needs_attention` and a message naming the offending paths instead of reviewing — and later committing — unrelated local edits as step work. A resumed step (already started, e.g. `changes_requested`) keeps its own in-progress tree. The output directory is also excluded from the reviewed diff and from intent-to-add, so the engine never reviews its own reports.
- **Approval commits are exact.** On PASS the engine re-reads the diff and refuses to commit when its sha256 differs from the final reviewed report's; it then stages (output dir excluded) and verifies the staged diff is byte-identical to the approved diff before committing. Any mismatch resets the index and stops the step as `needs_attention` — an approval commit can no longer contain anything the reviewers did not approve.
- Regression tests: dirty-tree refusal (agent never runs, HEAD unchanged, edits untouched), exact approval-commit contents, resumed-step behaviour, post-review tree mutation refusal. Suite: 43 tests. Full response: `review-2-response-2026-11-03.md`.

## 0.4.0 — 2026-11-03
- **GitHub PR integration** (`reviewloop pr --repo OWNER/REPO --number N`, or `--pr <url>`): fetches the PR's metadata and unified diff from the GitHub API and reviews the diff where the work lives. Read path needs no token on public repos. `--post` (needs `GITHUB_TOKEN`) posts the report as a PR review comment — COMMENT by default, REQUEST_CHANGES on a blocked gate only with `--request-changes`; the bot never auto-approves — and sets a `reviewloop` commit status on the PR head (success / failure / pending from the gate). `--verify-previous` runs the verification round against the PR's current diff, so the review → fix → verify loop works across pushes. Tokens come from the environment only, are never logged, and authenticated requests refuse redirects.
- Live proof: karpathy/llm-council PR #226 fetched and reviewed read-only with the real panel (gate PASS, degraded honestly labelled while one provider was quota-limited). The write path is covered by fake-transport unit tests; the first live post waits on our GitHub account reinstatement — that is the only account-gated piece.
- Self-review of this release: 3 majors raised, all three rebutted with code evidence in the verification round (the checks/timeout/no-retry-loop facts were already in the code), 1 minor fixed (table-cell newline collapsing in PR comments). 39 unit tests.

## 0.3.0 — 2026-11-03
The workflow spec's real gaps, closed:
- **Account pools with visible fallback rotation.** Repeating a reviewer seat (`--provider gemini --provider gemini`, or custom specs sharing a name) builds a pool: accounts are tried in order (preset accounts read `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, …), a quota/rate-limit/5xx/dead-key error rotates to the next account, and every report records which account served and each rotation (from → to → error). Never a silent substitution. Live proof: a dead first account rotated to the second, recorded in the report.
- **Multi-step workflow engine** (`reviewloop workflow --file wf.json`): ordered steps with the spec's states (queued / running / changes_requested / verifying / approved / needs_attention), each step gated by the full review loop; on PASS the step's change is committed as its approval record and the workflow advances. State persists in `workflow-state.json` — rerunning resumes (approved steps are skipped); a `STOP` file pauses between steps; owner waivers are read from the state's `waivers` map.
- **Owner waivers in the loop** (`--waive <finding-id>` or workflow-state waivers): waived blockers are recorded as `waived_by_owner` in the finding lifecycle and never sent to the builder.
- **Round-to-round change summary:** each loop round records its file list and the per-file line-count delta vs the previous round.
- Fixes found by the workflow tests and live runs: patches now include untracked files (intent-to-add) — a review blind to the agent's new files was the engine's worst failure mode; approval commits exclude the workflow's own output directory; JSON recovery hardened (repair retry + one fresh sample; prompts now ban double quotes inside string values, the main malformed-JSON cause).

## 0.2.1 — 2026-11-03
From the reviewer↔coding-agent workflow spec (same day):
- **Structured work-report contract enforced in the loop:** the builder packet now requires one disposition line per finding (`Finding <id>: fixed | rebutted | unresolved — evidence`); reports missing dispositions are flagged to the verification reviewers and recorded as `work_report_gaps` (they never clear a finding by themselves).
- **Finding lifecycle in `loop-result.json`:** every blocking finding ends as `fixed_verified`, `rebutted_accepted`, or `unresolved`, plus a `workflow_state` (approved / changes_requested / needs_attention) matching the spec's step states.

## 0.2.0 — 2026-11-03
- **Loop driver** (`reviewloop loop`): the full workflow as one command — reviewers review the working-tree diff; on BLOCKED, the findings packet is handed to a builder command (the coding agent: it receives `$REVIEWLOOP_PACKET`, edits the tree, writes its work report to `$REVIEWLOOP_RESPONSE`); a verification round then decides whether the workflow advances. Repeats up to `--max-rounds` builder rounds, then stops for a human. Writes per-round reports plus `loop-result.json` (`advanced: true` on PASS). Inconclusive rounds stop the loop — reviewer-infrastructure problems are never the builder's fault.
- Live proof (internal panel): planted alert-flood change BLOCKED on round 1, scripted builder fixed it with a dedup guard + work report, verification PASS on round 2, loop advanced.

## 0.1.1 — 2026-11-03
External review round 1 — both findings accepted and fixed:
- Verification resolutions are now validated: the status must be in the allowed set, and a `fixed`/`invalid` claim needs non-empty evidence that shares real vocabulary with the diff, test output, prior finding, or builder response. Unsupported assertions are downgraded to `unclear` (block stays) and marked in the report.
- `--strict` verification rounds now return INCONCLUSIVE when a reviewer failed (degraded), matching the documented strict behaviour of review rounds.
- Regression tests for both findings; suite is 18 tests.

## 0.1.0 — 2026-11-03
- Initial build: review → gate → verify loop.
- Deterministic scan (secrets, injection, data-loss, alert-guard, disabled tests, debug leftovers) + project test commands as blockers.
- Parallel provider review with correctness and operations lenses; consensus merge.
- Verification round: prior blockers clear only on unanimous reviewer agreement.
- Providers: Gemini, OpenAI, xAI, NVIDIA, DeepSeek presets + custom OpenAI-compatible specs.
- Secret redaction before provider calls (and in stored report evidence); diff treated as untrusted data in prompts.
- Provider JSON repair retry (one re-ask with an explicit escaping instruction) before a malformed reply counts as a provider error.
- Live-verified 2026-11-03 on the internal Gemini+NVIDIA panel: deliberately buggy fixture blocked with 7 blocking findings (hardcoded secret, SQL injection, unconditional deletion, alert flood); guarded fixture passed after one verification round.
