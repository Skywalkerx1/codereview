# Feedback on the Reviewer ↔ Coding Agent Workflow spec (2026-11-03)

Checked line-by-line against ReviewLoop v0.2.0. Verdict: the spec is
sound, and it independently describes the architecture we shipped the
same day — review → gate → findings to the agent → fix + work report →
verification → advance. Roughly the whole engine semantics are
already implemented and live-verified; the gaps are the app layer
around the engine.

## Already built (engine, v0.1.0–v0.2.0)

- Main workflow and detailed sequence steps 3–7, end to end, as one
  command (`reviewloop loop`), proven live 2026-11-03 (planted
  alert-flood BLOCKED → builder fix + report → verification PASS →
  advanced).
- Findings carry the spec's fields (severity, file/line, evidence,
  recommendation, reviewer identity) and keep their original IDs
  through every round; each report records the exact revision
  (`patch_sha256`).
- Findings close only on reviewer verification, never on the agent's
  word; the agent cannot approve its own work; reviewers judge the
  new diff, not the report (evidence validation, v0.1.1).
- Retry limit with a clear stop-for-human escalation state
  (`--max-rounds`); inconclusive rounds (provider outage) stop the
  loop instead of blaming the builder.
- Gate policies: blocking severities configurable; verification
  requires every successful reviewer to agree; provider failure is
  labelled `degraded`, and strict mode (the spec's gate default)
  refuses to advance on incomplete coverage.
- Secret redaction before any provider call, diff size limits,
  per-repo test commands whose failures block, Markdown + JSON
  reports, per-round history artifacts.

## Adopted from the spec today (v0.2.1)

- **Structured work report, enforced.** The builder packet now
  requires the spec's disposition format per finding
  (`Finding <id>: fixed | rebutted | unresolved — evidence`).
  Reports missing dispositions are flagged to the verification
  reviewers and recorded as `work_report_gaps`.
- **Finding lifecycle + step states.** `loop-result.json` now ends
  every blocking finding as `fixed_verified` / `rebutted_accepted` /
  `unresolved`, with a `workflow_state` (approved /
  changes_requested / needs_attention) from the spec's state list.

## Gaps accepted onto the roadmap

1. **Account switching.** Spec §"Reviewer accounts": manual switch +
   visible fallback after quota errors. Today the engine uses
   multiple providers but one account each, and degrades honestly
   rather than rotating. Account pools with a fallback order are now
   the top roadmap item (the LiteLLM pattern). The console prototype
   already demonstrates the intended UX.
2. **Multi-step workflows.** The spec makes ordered steps, templates,
   and pause/resume the app's job. Our loop advances one step and
   signals the harness (exit code / `advanced: true`); the workflow
   engine itself is future work, sequenced after the GitHub
   integration below.
3. **GitHub PR integration** (spec's first-release item 1): PR
   selection, review comments, status checks. Already on the
   roadmap; currently also blocked operationally by our GitHub
   account suspension (appeal in flight 2026-11-03).
4. **Round-to-round diff view, notifications, recorded owner
   overrides** — visibility-layer items; the console covers the
   screens as a prototype, none are wired yet.

## One deliberate difference

The spec's default gate treats any incomplete review (provider
failure) as non-advancing. That is our `--strict` mode. The default
stays non-strict for a practical reason seen on day one: a free-tier
reviewer sat on a 429 wall for an entire afternoon, and under the
spec's default nothing would have shipped that day even with a
healthy second reviewer in full agreement. Our compromise: degraded
rounds are labelled loudly in every report, and release gates should
run `--strict`. Open to revisiting once account pools make full
coverage the norm.
