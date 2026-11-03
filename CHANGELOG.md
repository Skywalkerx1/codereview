# Changelog

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
