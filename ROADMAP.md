# Roadmap

## v0.1 (now)
- Core loop: diff in → deterministic checks → parallel multi-model review → deterministic gate → verification round with consensus clearing.
- CLI with presets for Gemini, OpenAI, xAI, NVIDIA, DeepSeek + any OpenAI-compatible endpoint.
- Markdown + JSON reports. Unit tests with fake providers.

## Next (open source)
- **From the reviewer↔coding-agent workflow spec (2026-11-03):** account pools per provider with a configurable fallback order — on a quota/rate-limit error the next account takes the seat, visibly in the run history (the engine today degrades honestly but does not switch accounts); multi-step workflow templates (ordered steps with states: queued / running / awaiting review / changes requested / verifying / approved / failed) so a PASS advances the agent to the next step inside the app, not just signals the harness; round-to-round "what changed" diff view; an owner override action (waive a blocker) recorded in the audit history.
- Suppression comments (`# reviewloop: ignore <rule>`) so deliberately-buggy test fixtures and a scanner's own rule-definition strings don't have to be rebutted every round — the top lesson of the v0.1.0 self-review (2026-11-03).
- Global wall-clock budget per review round.
- GitHub integration: run as a PR check, post the report as a PR review comment, update on each push (verification rounds keyed to the PR).
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
