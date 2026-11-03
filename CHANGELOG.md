# Changelog

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
