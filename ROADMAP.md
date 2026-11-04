# Roadmap

## v0.8 (2026-11-04)
**Epic A landed**: the benchmark harness (`codereview bench run|report`) and corpus v0 (36 cases, 31 ground-truth defects, public/holdout split) ship in v0.8.0 — see `bench/README.md` for definitions and the growth path to 50–100 cases. Next per the adopted order: Epic B (policy file), with the corpus growing from real run records as they accumulate.

## v0.7 direction (adopted 2026-11-04)
The revised plan (first-principles edition) now governs: one promise — *a verifiable verdict on AI-written code, with a public record* — proven by numbers, not adjectives. Launch scope narrows to CLI + GitHub Action + public benchmark + public run pages. Epic order: **A. Benchmark harness + corpus** (seeded from our own stored run records + programmatic defect injection) → B. Policy file (TOML) → C. Evidence runner + builder-claim verification → D. Action/SARIF/mirrors → E. Risk-tiered panels → F. Injection/redaction suites → G. Public run pages. Console and iOS are frozen as internal surfaces; hosted tier, editor extensions, and MCP/A2A wait for demonstrated demand (week-12 decision, data-chosen). Agent seats (v0.7.0) make any local agent CLI — Claude Code, Codex, Grok bots — a reviewer or solver, which is also how the panel gains vendor families without new API keys. v0.7.1 closed the v0.7.0 external review's required fixes (agent env allow-list, verification quorum + original-finder rule + visible DEGRADED labels, scratch-dir seats, seat namespaces, process-group lifetimes); **no new surfaces until Epic A lands.** Still open: a recorded run with a real agent CLI (needs a machine with one installed — this VM has none) and per-seat family metadata, which lands with Epic E's diversity enforcement.

## v0.1 (now)
- Core loop: diff in → deterministic checks → parallel multi-model review → deterministic gate → verification round with consensus clearing.
- CLI with presets for Gemini, OpenAI, xAI, NVIDIA, DeepSeek + any OpenAI-compatible endpoint.
- Markdown + JSON reports. Unit tests with fake providers.

## Next (open source)
- **From the reviewer↔coding-agent workflow spec (2026-11-03) — DONE in v0.3.0:** account pools with fallback rotation recorded in run history; multi-step workflow engine (ordered steps, spec states, resume, approval commits); round-to-round change summaries; owner waivers recorded in the finding lifecycle. Still open from the spec: notifications, and the hosted console wiring (the console is a session-only prototype). **GitHub PR integration DONE in v0.4.0** — PR fetch/review, review comments, commit status, verify-previous across pushes; the write path is unit-tested and its first live post waits only on our GitHub account reinstatement.
- Fixture scope — DONE in v0.9.0 for the data-file half of this lesson, as classification rather than exclusion: a versioned fixture manifest enumerates the deliberately-buggy fixture DATA (benchmark corpus, canned seat responses); record runs classify their findings as expected fixture findings in the record (evidence preserved, non-blocking), and `record-verify` recomputes the manifest hash, policy version, and classified paths against the reviewed range. Still open: suppression comments (`# codereview: ignore <rule>`) for a scanner's own rule-definition strings inside product code — the other half of the top lesson of the v0.1.0 self-review (2026-11-03).
- Global wall-clock budget per review round.
- ~~GitHub integration~~ DONE in v0.4.0 (see above). Follow-ups: update the posted comment in place instead of adding a new one per push; GitHub Checks API (richer than commit statuses).
- More lenses (API-contract, migrations, i18n) and per-path lens routing.
- Reviewer calibration: track which reviewers' findings prove real (confirmed in verification / post-merge incidents) and weight consensus accordingly.
- Local-model providers (Ollama) for fully private review.
- SARIF output for code-scanning dashboards.

## Later (hosted / subscription)
- Hosted service: zero-setup PR reviews, team policies (which severities block which repos), reviewer assignment rules.
- History & analytics: block rate, repeat-finding patterns, per-builder and per-reviewer stats.
- Private-repo handling with customer-managed keys, audit logs, SSO.
- Incident feedback loop: post-merge incidents auto-linked back to the review that passed the change.

The core loop stays open source. The hosted layer is where subscriptions will live, once the feature set earns it.
