# Roadmap

## v0.1 (now)
- Core loop: diff in → deterministic checks → parallel multi-model review → deterministic gate → verification round with consensus clearing.
- CLI with presets for Gemini, OpenAI, xAI, NVIDIA, DeepSeek + any OpenAI-compatible endpoint.
- Markdown + JSON reports. Unit tests with fake providers.

## Next (open source)
- **From the reviewer↔coding-agent workflow spec (2026-11-03) — DONE in v0.3.0:** account pools with fallback rotation recorded in run history; multi-step workflow engine (ordered steps, spec states, resume, approval commits); round-to-round change summaries; owner waivers recorded in the finding lifecycle. Still open from the spec: notifications, and the hosted console wiring (the console is a session-only prototype). **GitHub PR integration DONE in v0.4.0** — PR fetch/review, review comments, commit status, verify-previous across pushes; the write path is unit-tested and its first live post waits only on our GitHub account reinstatement.
- Suppression comments (`# codereview: ignore <rule>`) so deliberately-buggy test fixtures and a scanner's own rule-definition strings don't have to be rebutted every round — the top lesson of the v0.1.0 self-review (2026-11-03).
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
