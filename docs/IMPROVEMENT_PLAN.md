# CodeReview improvement plan

Cycle 1, 2026-11-11. Branch `improvement-plan-1`, based on v0.13.3 (`c2cb0e5`). Written by Missy (reviewer and tester seat) at the owner's request.

## Bottom line

CodeReview is for solo developers checking code their AI agent wrote. Each user picks **one reviewer (the default) or a multi-reviewer panel**, whatever the project's size.

1. **Done on this branch:** the review-mode choice and the same-vendor warning. Neither changes a gate rule or a verdict.
2. **Next, and the one that matters most:** a solo gate profile, so a single reviewer stops blocking most clean changes. It ships only behind an off-by-default flag until its own registered benchmark passes, because it can weaken the gate.
3. **Then:** a first run with no API keys, a GitHub Action for pull requests, per-review cost in the record, and the agent loop as the homepage story.

## Verification status (read this before relying on the branch)

- **One check, not two.** For this cycle the same agent (Missy) wrote, reviewed and tested the code. The team's §6 rule wants an author, a separate reviewer and the tester. This branch has had one check, not two independent ones. A second person or seat should review it before it merges.
- **Tests were not run.** The authoring sandbox refused to execute the repository's code, so the full suite and the new `tests/test_review_modes.py` were written and byte-compiled (`python -m py_compile`) only. Nothing on this branch has been executed.
- **Lint was not run.** ruff and mypy are not installed in the authoring sandbox. The 18 ruff and 8 mypy findings deferred at 0.13.3 are untouched.
- **Run before merging** (from the repo root, Python 3.11+):

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest tests.test_review_modes -v
ruff check src tests && mypy src
```

Record the counts here when they run. Until then the branch is NOT READY.

### v0.13.3 macOS baseline (before this branch)

Jeremy ran the suite on his Mac on 2026-11-11 (macOS, Python 3.14) on his v0.13.3 checkout, because the bundle had not been downloaded yet. Result: Ran 1662 tests, FAILED (failures=5, errors=1, skipped=11). None of the six touch files this branch changes. Compare the branch run against this list: only a failure outside it counts against the branch.

- `test_herdr_plugin` `test_outside_herdr_falls_back_to_cwd` and `test_pass_run_streams_verdict_record_and_exits_zero`: the temp dir resolves to `/private/var/...` while the test expects `/var/...`. A test-only symlink mismatch; the fix is to compare `os.path.realpath` on both sides.
- `test_phase3_security` `test_make_non_dumpable_idempotent`: `hardening.make_non_dumpable()` is Linux-only by design and returns False on macOS. The test should skip off Linux, and the docs should say this hardening does not apply on a Mac.
- `test_probe_harness` `test_limits_applied_inside_probe` and `test_memory_limit_bounds_allocation`: the probe's RLIMIT_AS (2 GiB) is not applied on macOS (the probe reports `as 9223372036854775807`), and `_set` swallows the error. So the probe's memory cap is not enforced on a Mac. This matters for the solo-developer audience, many of whom run on Macs; either enforce a cap another way or skip the tests off Linux and say so in the docs.
- `test_phase3_security` `McpNestedFrameTests.test_deeply_nested_frame_gets_parse_error`: KeyError 'error'. Inferred, not verified: the MCP transport relies on `RecursionError` to reject a frame nested 50,000 deep, and Python 3.14 appears to parse it without raising, so the frame is answered instead of refused. If that holds, add an explicit nesting-depth check rather than relying on the interpreter's recursion limit.

## Goals and who it's for

**Who:** a solo developer whose AI coding agent (Claude Code, Codex, Gemini CLI, Grok and the like) writes most of the code, and who wants a second opinion that is not the same model grading its own work.

**What they need from CodeReview:**

- A setup that takes minutes, starting with one reviewer and one key, or none.
- A verdict they can act on: PASS, BLOCKED with a reason they can check, or INCONCLUSIVE with a clear "you decide".
- Few false blocks. Today the default `strict` profile blocked 32 of 34 clean changes in registered testing (bench/generation-v2/RESULTS-2026-11-05.md, a run that failed its clean-change threshold), which a solo developer will not tolerate for long.
- A way to add more reviewers later when the stakes are higher, without switching tools.

**Goals for the next cycles:**

1. A new user gets a first verdict within 10 minutes of `pip install`.
2. Single-reviewer mode blocks far fewer clean changes without letting real defects pass.
3. Every number the product publishes stays traceable to a named record.

## The two modes and how a user picks

| | Single reviewer (default) | Multi-reviewer panel |
|---|---|---|
| Seats | Exactly one | Two or more, ideally from different vendors |
| Cost and time per review | Lowest | Roughly one call set per seat |
| Cross-checking | None between vendors; deterministic checks and your tests still gate | Findings are cross-examined across vendor families; a Tech Lead seat can adjudicate disputes |
| Gate profiles available | `strict` (today); `solo` once it passes its benchmark | `strict`, `balanced`, `corroborated` |
| Good for | Everyday changes, fast iteration | Payments, auth, data deletion, releases, anything you can't afford to get wrong |

**How a user picks.** `codereview setup` asks first, with single as the default. The choice is saved and can be changed by re-running setup, or per run with `--review-mode single|panel`. A simple rule of thumb for the docs: start single; switch a run to the panel when the change touches money, auth, secrets, deletion or a release.

**Always pick a reviewer from another vendor than the coding agent.** Setup now asks which vendor writes the code and warns on a match. A same-vendor reviewer is closer to self-review.

## Build order

Each item lists why, acceptance criteria, and how I will verify it as tester. Items 1 and 2 are on this branch.

### 1. Review mode as the user's choice (done on this branch)

**Why:** the owner's decision. Today setup has no notion of mode and says "any two providers are a good start", which reads as if one reviewer is wrong.

**What changed:**

- `codereview setup` asks single (default) or panel first. Single takes exactly one seat and skips the five role prompts; panel takes two or more and keeps them.
- The saved setup gains a top-level `review_mode`. A file without it is byte-identical to before, and a mode that does not fit the saved providers fails loudly.
- The gate and `loop` take `--review-mode single|panel` and refuse a seat count that does not fit before anything is sent. The saved mode applies only when the providers come from the saved setup, so explicit `--provider` flags and `$CODEREVIEW_PROVIDERS` keep working as before.
- The gate records `review_setup.review_mode` in the run record.

**Acceptance criteria:**

- Fresh setup with Enter at the mode prompt saves `review_mode = "single"` and one provider.
- Single mode with two seats and panel mode with one seat exit 2 with a plain message, and make no provider call.
- An existing config without `review_mode` behaves exactly as at 0.13.3.
- The full suite passes unchanged.

**How I verify:** run `tests/test_review_modes.py` and the full suite; run `codereview setup` by hand twice (single and panel) in a throwaway `$CODEREVIEW_CONFIG`; diff a pre-existing config file before and after a run to confirm it is untouched.

**Known gaps:** `codereview pr`, `workflow`, `intake` and `doctor` don't take `--review-mode` yet. A `--role` assignment that adds a second seat in single mode is not refused.

### 2. Same-vendor warning (done on this branch)

**Why:** a reviewer from the coding agent's own vendor tends to share its blind spots. That is the product's founding point, and nothing told the user today.

**What changed:**

- Setup asks which vendor's model writes the code (Enter skips) and warns when a reviewer seat matches. It is saved as `builder_family`.
- The gate and `loop` take `--builder-family` and print a stderr warning naming matching seats. `loop` also infers the vendor when `--builder-cmd` runs `claude`, `codex` or `gemini`.
- The gate records `review_setup.builder_family` and `review_setup.same_vendor_seats`.
- Seats whose family can't be attributed (generic agent seats, local models) never match, so the warning names only what it can stand behind.

**Acceptance criteria:** a matching seat produces exactly one warning line and the verdict and exit code are unchanged; no match and no builder family produce no output and no `review_setup` key.

**How I verify:** the new tests, plus one real run with `--builder-family anthropic --provider anthropic` and a diff of the record against the same run without the flag. Only `review_setup` may differ.

### 3. Solo gate profile (next; off by default until its benchmark passes)

**Why:** single mode today runs `strict`, which blocks most clean changes. The `corroborated` profile can't help because it needs two vendor families.

**Proposal (Mike's item 1, adjusted):** a new profile, `solo`, selectable with `--gate-profile solo`, never the default until it passes. Under it:

- Deterministic findings (E0), failing test commands and probe-confirmed findings (E2) still block, exactly as today.
- A model major that is not corroborated becomes **INCONCLUSIVE**, never PASS and never silently minor.
- In single mode, "corroborated" means **recurrence**: the same seat is re-asked k = 3 times and the finding recurs in at least 2. The Stage-0 P-C falsifier run is the evidence base (bench/stage0-pc/RESULTS-2026-11-07.md): clean blocking findings recurred 7 of 32 times (0.219), defect findings 10 of 17 (0.588).
- Model blockers: open question for the owner (see below). My recommendation is that they follow the same rule as majors.

**The risk, stated plainly:** INCONCLUSIVE weakens the gate if users treat it as "probably fine". Under a pure recurrence gate, 2 of the 8 blocked defect cases in the P-C run would have flipped to pass (`clean-input-validation`, `race-check-then-act`). Under `solo` they become INCONCLUSIVE, which only holds if the user reads them. The rejected `quiet` profile is the cautionary case: blanket demotion let three real single-seat majors through.

**Benchmark it needs before it ships (registered, thresholds stated before the first call):**

| Metric | Threshold | Why |
|---|---|---|
| Defect cases ending in PASS | 0 among blocking-tier defects | INCONCLUSIVE is the most it may concede |
| Blocking-tier defects BLOCKED (not just INCONCLUSIVE) | ≥ 0.60 | Same bar `corroborated` failed at 0.292 (bench/confirmation-b2/RESULTS-2026-11-06.md) |
| Clean changes BLOCKED | point ≤ 0.20, Wilson 95% upper ≤ 0.30 | The registered clean bar `strict` failed |
| Clean changes INCONCLUSIVE | ≤ 0.40 | Otherwise noise just moves from BLOCKED to INCONCLUSIVE |
| Replay of the three `quiet` cases (D6–D8) | none PASS | The known failure mode |

**Sample size:** the clean stratum needs about 80 or more scored clean cases. At 34 (today's expanded-clean set) even a 0.20 point estimate has a Wilson upper above 0.30, so the run could not certify a pass. Growing the clean corpus is part of this item.

**Acceptance criteria:** the registered run passes every row above; the record names the profile, k, and per-finding recurrence counts; `strict` stays the default until the owner rules.

**How I verify:** I check the pre-registration is dated before the first call, recompute every row from the raw records, and rule READY or NOT READY on the exact commit. The same agent should not both build and certify this one.

### 4. A first run with no API keys

**Why:** the fastest path to "it works" is a verdict before any signup.

**Three routes, in order of effort:**

1. `codereview demo`: runs the deterministic layer on two bundled samples (`examples/buggy_alert_flood.patch` should block on the hardcoded password, the f-string SQL delete and the unguarded alert email; `examples/clean_change.patch` should not) and writes a real record. It says plainly that no model reviewed anything. The samples must move into the package: today `examples/` ships in the sdist but not in the wheel, which only carries `src/`.
2. An agent seat using the CLI login the user already has (Claude Code, Codex, Gemini CLI). This exists today via setup's discovery step; the docs should lead with it.
3. A local model (`ollama`, `lmstudio`). Exists today; keyless and offline.

**Acceptance criteria:** in a fresh virtualenv with no key variables and outbound network blocked, `codereview demo` exits 1 on the buggy sample, 0 or 2 on the clean one, writes both records and makes zero network calls.

**How I verify:** a test with a socket guard that fails on any connect, plus one manual run on a machine with the network off.

### 5. GitHub Action for pull requests

**Why:** solo developers live in pull requests; an Action makes the review automatic.

**Shape:** a workflow template (later a published action) that installs `codereview-loop`, runs `codereview pr --pr <url> --post`, and sets the `codereview` commit status. Keys come from repository secrets.

**Security requirements:** trigger on `pull_request`, never `pull_request_target` with a checkout of the PR head, so a fork's PR can't run with the repo's secrets. Default `--review-mode single` with one secret.

**Acceptance criteria:** on a test repository, opening a PR posts one review comment and a commit status within the job; a second push runs `--verify-previous`; a fork PR runs without secrets and reports INCONCLUSIVE rather than failing open.

**How I verify:** read the workflow for the trigger and permissions, then watch one live PR end to end. Note: the README still says the PR command has not been tested on a live PR; that test comes first.

### 6. Per-review cost in the record

**Why:** single versus panel is partly a cost decision, and today the record says `cost: not_available`.

**Shape:** each API provider returns token usage (OpenAI-compatible `usage`, Anthropic `usage`, Gemini `usageMetadata`); the record gains measured tokens per seat and an estimate in USD from a versioned price table. Agent seats and local models stay `not_available` rather than guessed.

**Acceptance criteria:** a run's record shows tokens in and out per seat that match the provider responses; the estimate names its price-table version; nothing is invented when a provider returns no usage.

**How I verify:** recorded fake responses with known usage in tests, and one live run compared against the provider's own usage page. This touches the record schema, a sensitive surface, so it needs an additive schema bump (1.1.0) and a second reviewer.

### 7. The agent loop as the homepage story

**Why:** "your agent writes, another model reviews, your agent fixes, the gate decides" is the product in one sentence, and `codereview loop` already does it.

**Shape:** README and PyPI page open with a 3-command loop example in single mode, then the panel as the upgrade.

**Acceptance criteria:** every product claim on the PyPI page stays quoted from `PYPI-README.md`; every "tested" sentence names its version; numbers link to their records.

**How I verify:** a claims check of the new text against the records, as with the launch posts.

### 8. Housekeeping that a new user notices

- The repository root holds about 70 `review-*` output folders and logs. Move them under `records/` or out of the default branch.
- README "Status" still says v0.13.1, and the PyPI page's release-notes link goes to v0.13.1.
- Reconcile the clean-block figures in team notes: the briefing's "about 65%" is the `balanced` profile's figure (22 of 34), while the README headline is the default `strict` profile's 32 of 34 (bench/generation-v2/RESULTS-2026-11-05.md). Wherever the default is described, keep `strict`'s figure.
- The deferred 18 ruff and 8 mypy findings.
- The old Show HN draft still in the team's to-duet folder.
- The six macOS baseline failures listed under Verification status: make the suite pass on macOS and Python 3.14, which is where solo developers will first run it.

## User workflows

### A. Single reviewer (the default)

1. `pip install codereview-loop`
2. Export one key, from a different vendor than your coding agent: `export GEMINI_API_KEY=...`
3. `codereview setup`: press Enter for single reviewer, enter `gemini`, then name your coding agent's vendor (for example `anthropic`).
4. Stage your agent's change and run `codereview --repo . --staged --test-command "python -m pytest -q"`.
5. Read the verdict: exit 0 PASS, 1 BLOCKED (fix or waive with a reason), 2 INCONCLUSIVE (you decide).
6. Optional: let the agent fix its own findings with `codereview loop --repo . --builder-cmd "<your agent command>"`.

### B. Single reviewer with no API keys

1. `pip install codereview-loop`
2. Planned: `codereview demo` to see a real verdict on bundled samples, deterministic checks only.
3. `codereview setup`: Enter for single, then accept the agent CLI that discovery found (for example Codex, using your existing login), or enter a local model such as `ollama`.
4. Run reviews as in workflow A, steps 4 to 6. Pick a seat whose vendor differs from your coding agent, or the setup will warn you.

### C. Multi-reviewer panel

1. Export two or more keys from different vendors.
2. `codereview setup`: choose 2 (panel), enter at least two providers (for example `gemini, deepseek`), name your coding agent's vendor, then accept or override the per-role models (put the Tech Lead on a third vendor if you can).
3. Run `codereview --repo . --range main...HEAD --test-command "<tests>"`.
4. Optional: `--gate-profile balanced` or `corroborated` for fewer false blocks (note `corroborated` failed its registered run and is dev evidence only).
5. For a one-off high-stakes change with a single-reviewer setup: `codereview --review-mode panel --provider gemini --provider deepseek ...`.

### D. GitHub Action on pull requests (planned, item 5)

1. Add the reviewer's key as a repository secret.
2. Copy the workflow template into `.github/workflows/`.
3. Open a pull request: the Action posts a review comment and sets the `codereview` status.
4. Push a fix: the Action re-runs with `--verify-previous` against the earlier report.
5. Optional: make the `codereview` status required in branch protection.

## Open questions for Jeremy

1. **Solo profile and blockers:** should an uncorroborated model *blocker* also become INCONCLUSIVE under `solo`, or keep blocking? I'd treat it like a major.
2. **Default profile in single mode:** once `solo` passes its benchmark, should it become the default for single mode, or stay opt-in?
3. **Benchmark spend:** the solo benchmark needs about 80 more clean cases and k = 3 samples per finding. Do you approve a spend cap for it?
4. **Second reviewer for this branch:** who reviews it before merge, given Richard is unavailable?
5. **Repository clean-up:** may the `review-*` folders move off the default branch?

## Sources and what was inferred

**Read:** the PyPI page for codereview-loop 0.13.3; the repository at `c2cb0e5` (README, ROADMAP, CHANGELOG, `bench/generation-v2/RESULTS-2026-11-05.md`, `bench/confirmation-b2/RESULTS-2026-11-06.md`, `bench/stage0-pc/RESULTS-2026-11-07.md`, `src/codereview/setup_wizard.py`, `userconfig.py`, `registry.py`, `discovery.py`, `cli.py`); the team's launch-status and briefing notes of 2026-11-10 and 2026-11-11; Mike's revised plan of 2026-11-11.

**Inferred, not measured:** the 80-case clean-stratum size (from the Wilson bound at a 0.20 point estimate); that INCONCLUSIVE is often skimmed past by solo users; the GitHub Action's security shape. The benchmark thresholds are my proposal, modelled on the registered thresholds used before.
