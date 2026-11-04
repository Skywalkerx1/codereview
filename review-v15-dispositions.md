# review-v15 dispositions — Phase 3 closing run, round 1 (attempt 11)

Record: `review-v15/codereview-20261104-224759.json`, span
`3013656..e3fc6a8` (v0.9.3, head `e3fc6a8c12bae345ce0102933b90f47bd874d862`),
patch sha256 `1117c888a850f4ff35d8d6158380564a7d24a9553655b2bf4943bd12f731c8df`.
Preflight (doctor, exact review shape): Gemini quota 429 (not retried) →
OpenAI fallback healthy on correctness; NVIDIA healthy on operations —
the expected healthy shape. Gate: **BLOCKED**, degraded = true.
`record-verify`: 9/12 — failures are `gate_pass`, `not_degraded`,
`coverage_complete`. Full output: `review-v15/record-verify.txt`.

The new machinery behaved as designed and is not dispositioned here:
9 findings withdrawn by their own seats in the re-ground pass, 5
standing findings auto-linked under content-addressed precedent, 44
expected fixture findings classified under the manifest — all
preserved as visible states in the record.

## Coverage: the degraded cause, identified exactly

`coverage_complete` fails on ONE truncated section, with **0 file/lens
omissions** (every file reached both lenses in 9 batches).
`src/codereview/core.py`'s cumulative diff over the span is 94,494
chars — larger than the 80,000-char per-batch budget — and
`_batch_sections_detailed` truncates a single oversized section
instead of sub-splitting it (core.py §_batch_sections_detailed:
`text = text[:max_chars]`). The next-largest section is 32,790 chars.
This is a machinery defect the closing run exposed, **not** a panel
finding, and it is not cured by this round: fixing it (sub-split
oversized sections at hunk boundaries) requires a fresh round 1
afterwards, which is outside this run's protocol (one round 1 +
verification rounds over fix ranges). It is recorded here and in the
successor issue report as the first build item of the next round.

## Blocking findings (5 majors) — all rebutted on executable evidence

| # | ID | Seat | Disposition |
|---|----|------|-------------|
| 1 | `636ba66423e7` | nvidia | **Rebutted — false positive.** "Fallback seats ignore configured agent timeout during review runs." The review command's fallback construction forwards it: cli.py:698-699 `build_providers([pspec.strip()], agent_timeout=args.timeout)` — the record's evidence quote shows only the first line of the call. The review primary forwards it too (cli.py:676-677), as do the verify/doctor constructions (1066-1067, 1101-1102). The three sites that build without `agent_timeout` (cli.py:238 `_loop_main`, 338 `_workflow_main`, 562 `_pr_main`) belong to commands whose parsers have no `--timeout` option at all — exactly the allowlist the v0.9.1 enumeration test guards. Pinned by `tests/test_v091_fixes.py` (enumeration) and `tests/test_v094_probes.py::FallbackTimeoutForwardingTests`. |
| 2 | `ec5d130cc37e` | nvidia | **Rebutted — false positive.** "No timeout guard on provider calls." Every provider call path carries one: API calls go through the single opener site, `_post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT)` with `DEFAULT_TIMEOUT = 240` (providers.py:37, 58-65); agent calls take the configured timeout and the seam rejects non-positive values loudly (providers.py:250-255, the v0.9.2 fix). AST probe pins the single-opener fact: `tests/test_v094_probes.py::ProviderTimeoutTests`. |
| 3 | `ca7b6fb25b54` | nvidia | **Rebutted — false positive.** "Retry policy lacks hard per-job attempt cap." `_call_with_retry`'s `while True` is bounded on every path: per-class caps from `_classify_error` (quota/auth/unknown = 1, rate_limit/transient = 3), min'd with `max_attempts` when given, raising as soon as `tally["attempts"] >= max_tries`; the job level enforces `_MAX_JOB_ATTEMPTS = 6` by handing the fallback only the REMAINING budget (core.py:1036). Property probes (always-failing seat stops at exactly 3 / 1 / 2 attempts): `tests/test_v094_probes.py::RetryBoundTests`. Same substance as the v12 [6]/[7] rebuttals, re-verified against current code. |
| 4 | `3fbb6b031f51` | nvidia | **Rebutted — false positive.** "_classify_error regex may misclassify error codes." The quoted line IS the v0.9.3 fix for v14 [9]: `has_code` matches whole tokens (`\b{code}\b`) and typed provider codes are checked before message text. Probes: a 503 body mentioning "4030 tokens" stays transient; "req_4014" is not a 401; `insufficient_quota` classifies quota with no 429 present (`tests/test_v094_probes.py::ClassifyErrorTokenTests`, plus the v0.9.3 table tests). The finding offers no concrete misclassifying input. |
| 5 | `320b878c6253` | openai | **Rebutted — false positive.** "Successful agent runs can be reported as failures due to unconditional post-exit kill." `_kill_tree` cannot raise on a dead group: it catches (ProcessLookupError, PermissionError, OSError) and its fallback `proc.kill()` is separately guarded (providers.py:180-197); and `communicate()` has already captured `proc.returncode` before the `finally` runs, so the kill cannot change the verdict the code then reads. The post-exit group kill is required behavior (v0.7.1 finding 3.2: an agent's background children die with their seat). Live probes: `tests/test_v094_probes.py::KillTreeTests` (dead-process kill never raises; a successful agent run returns its output). Same substance as the v12 [0] blocker rebuttal; precedent did not auto-link it because providers.py's blob legitimately changed in v0.9.2/v0.9.3 — content-addressing working as intended. |

No product-code defect was found among the five blockers; nothing was
"confirmed" or "admitted" — each rebuttal above cites the lines and
is pinned by an executable probe in `tests/test_v094_probes.py`
(suite 264/264 with them).

## Minors (5)

| # | ID | Disposition |
|---|----|-------------|
| 6 | `2037144445ab` | **Rebutted.** "Cross-family confirmation description is ambiguous about quote validation" (CHANGELOG.md). The v0.9.3 entry states the rule verbatim: "Refute counts only with a quote that validates against the region" (CHANGELOG.md, 0.9.3 entry). No ambiguity found at the cited text. |
| 7 | `07c80cba9033` | **Standing repeat.** Deterministic "test disabled" hit on guard text quoted inside `precedents.json` — the precedent store's own adjudication data. Same substance as the guard repeats in v11-v14; the guard is unchanged. |
| 8 | `3f27ed23fbdc` | **Rebutted.** "Random import without deterministic seeding" (core.py): the `random.uniform(0, 0.25)` jitter in `_call_with_retry`'s backoff is intentional — it decorrelates concurrent seat retries; determinism is not a property the retry policy wants, and attempt counts remain hard-bounded (see [3]). |
| 9 | `a6f6e208bc99` | **Rebutted.** The local `import resource` inside `_limit_files` is deliberate: `preexec_fn` executes in the forked child, where a local import is the safe pattern. Harmless, by design. |
| 10 | `ff4f08624ea7` | **Standing repeat.** The POSIX `skipUnless` guard in `tests/test_v093_phase2.py` — the same guard line the deterministic scan re-derives every span (v11 [39] lineage). Guard unchanged. |

## Disputed findings (14 majors) — HUMAN GATE, not adjudicated here

Per the adopted §2c semantics, a finding refuted cross-family with a
valid quote leaves the blocking set but is **not** cleared:
`record-verify --chain` does not count disputed findings as
dispositioned, and this round does not resolve, waive, or accept any
of them. They are the owner's decision point, presented in full
(finding, both families' positions, quote evidence) in the closing
report and the successor issue report. IDs: `3c39c4bdc15a`,
`2fa2b04e08d5`, `474297e6ffdc`, `09c536d15270`, `bca4074a632c`,
`eae8137a6db3`, `3fc4862824c9`, `3cecf66f6ce5`, `d93089253022`,
`c5f02551d077`, `0e57186e8be8`, `1aec997aaec4`, `0ad4ed7db98e`,
`2242edbba9c9` — all preserved verbatim in the record's
`disputed_findings`.
