# ReviewLoop

**One agent builds. Independent models review. A deterministic gate decides.**

ReviewLoop is a multi-model code review loop for teams where AI agents write a growing share of the code. A single model reviewing its own work rubber-stamps it; a human reviewing everything becomes the bottleneck. ReviewLoop puts the change in front of *other* models — with different providers, different lenses — and lets code, not vibes, decide whether it ships.

```
builder ──diff──▶ deterministic checks ──▶ reviewer A (correctness/security)
                      (secrets, injection,        │
                       data-loss, your tests)     ▼
                                            reviewer B (operations/reliability)
                                                  │
                              ┌───── gate ◀───────┘
                              │  PASS / BLOCKED / INCONCLUSIVE
                              ▼
              fix or rebut ──▶ verification round ──▶ PASS only when
                                                         every reviewer agrees
                                                         the block is resolved
```

## Why

- **Self-review is not review.** The model that wrote the code shares its blind spots. Independent providers catch different things.
- **LLM opinions are not a gate.** Findings are structured, merged across reviewers (consensus raises confidence, never lowers severity), and the pass/block decision is made by deterministic rules over those findings.
- **Alerts about the loop itself can't flood you** — the same dedup discipline ReviewLoop checks for in your code is part of its own design brief (see the `alert-no-guard` rule, born from a real incident: an hourly checker that emailed on every run while the same violation persisted for weeks).

## Quick start

```bash
pip install reviewloop        # or: pip install -e . from a clone

export GEMINI_API_KEY=...     # any two providers are a good start
export OPENAI_API_KEY=...

# Review the staged diff in the current repo
reviewloop --repo . --staged --provider gemini --provider openai

# Review a patch file, with your test suite as a first-class input
reviewloop --patch change.diff \
  --provider gemini --provider xai \
  --test-command "python -m pytest -q" \
  --context "Adds retry logic to the payment webhook handler"

echo $?   # 0 = PASS, 1 = BLOCKED, 2 = INCONCLUSIVE
```

The report lands in `reviewloop-out/` as Markdown (for humans) + JSON (for tooling).

## Account pools — when a free quota dies, the next account reviews

Repeat a seat to give it several accounts:

```bash
export GEMINI_API_KEY=...        # account 1
export GEMINI_API_KEY_2=...      # account 2
reviewloop --repo . --provider gemini --provider gemini --provider nvidia
```

Accounts are tried in order; a quota, rate-limit, 5xx, or dead-key error rotates the seat to the next account. Every report records **which account served and each rotation** (from → to → error) — fallback is visible in the run history, never silently substituted. If every account fails, the seat degrades honestly and the gate says so. Custom specs sharing a name pool the same way (one account per spec, labelled by its key env).

## Multi-step workflows

```bash
reviewloop workflow --file workflow.json --repo . --out wf-out
```

`workflow.json`: `{"steps": [{"id": "db", "title": "Add the schema", "agent_cmd": "…", "test_commands": ["…"]}]}`. Steps run in order; each step's change goes through the full review loop; on PASS the change is **committed as the step's approval record** and the workflow advances to the next step. State persists in `wf-out/workflow-state.json` — rerun to resume (approved steps are skipped), touch `wf-out/STOP` to pause between steps, and record owner waivers under the state's `waivers` map (`{step_id: [finding_id, …]}`).

**Working-tree isolation:** a step that is starting fresh requires a **clean working tree** — commit or stash local edits first; the engine stops with a clear message rather than reviewing or committing changes that are not the step's. (A resumed step keeps its own in-progress changes.) The approval commit is verified byte-for-byte against the diff the reviewers approved; if the tree changed after the final review round, the commit is refused. The commit itself is assembled in a **temporary Git index**, so a refusal never alters your real index — staged work you had before the run is exactly where you left it.

## GitHub pull requests

```bash
reviewloop pr --repo OWNER/REPO --number 123                 # read-only review
reviewloop pr --pr https://github.com/OWNER/REPO/pull/123 --post
```

Fetches the PR's metadata + unified diff from the GitHub API and reviews it in place. Read-only works without a token on public repos. `--post` (needs `GITHUB_TOKEN` with repo access) posts the report as a PR review comment — COMMENT by default; `--request-changes` escalates a blocked gate to REQUEST_CHANGES; the bot never auto-approves — and sets a `reviewloop` commit status on the PR head (success / failure / pending). Re-run with `--verify-previous report.json` after a push to run the verification round against the new diff.

## The loop driver — the full workflow in one command

```bash
reviewloop loop --repo . \
    --builder-cmd "your-coding-agent-command" \
    --provider gemini --provider nvidia --max-rounds 3
```

1. Reviewers review the working-tree diff. **PASS → the workflow advances** (exit 0).
2. On BLOCKED, the findings are written to `$REVIEWLOOP_PACKET` (JSON) and your builder command — the coding agent — is invoked. It edits the working tree and writes its **work report** (per finding: what changed, with test evidence) to `$REVIEWLOOP_RESPONSE`.
3. A verification round checks the fixes against the new diff. PASS advances; BLOCKED loops back to the builder.
4. After `--max-rounds` builder rounds without a PASS, the loop stops and hands back to a human. A round that cannot complete (reviewer outage) stops the loop as INCONCLUSIVE — infrastructure problems are never blamed on the builder.

Per-round reports land in `round-1/`, `round-2/`, … and `loop-result.json` summarizes the run (`advanced: true/false`).

## The verification round

A blocked change is fixed — or rebutted with evidence — and re-checked:

```bash
reviewloop --patch fix.diff \
  --verify-previous reviewloop-out/reviewloop-20261103-150000.json \
  --builder-response @response.md \
  --provider gemini --provider openai
```

A prior blocker clears **only when every successful reviewer agrees** it is fixed (with evidence in the new diff) or was invalid. A split verdict keeps the block. The builder can never approve their own work — that rule is the product.

## Providers

Any two (or more) independent models. Presets: `gemini`, `openai`, `xai` (Grok), `nvidia`, `deepseek`. Any OpenAI-compatible endpoint works too:

```
--provider "mine|openai-compatible|https://api.example.com/v1|model-id|MY_KEY_ENV"
```

Keys come from environment variables only. Secrets in the diff are redacted before anything is sent to a provider, and the diff is treated as untrusted data — reviewers are instructed to ignore instructions embedded in code and comments.

## Gate semantics

| Gate | Meaning |
|---|---|
| `PASS` | No blocking findings (blockers, and majors by default; `--allow-major` relaxes majors to advisory) |
| `BLOCKED` | A blocking finding stands — from a model reviewer, a deterministic rule, or a failing test command |
| `INCONCLUSIVE` | Reviewers unavailable, or (with `--strict`) the review was degraded/truncated — a human decides |

Provider failure degrades the review (noted in the report); it never silently passes a change, and in `--strict` mode it blocks the pass.

## Deterministic checks (no model required)

Hardcoded secrets · AWS keys · private keys · `eval`/`exec` · `DROP TABLE` · string-built SQL · `DELETE` without `WHERE` · shell execution · alerts/notifications with no dedup/cooldown/state guard · disabled tests · debug leftovers · your own test commands as blockers.

## Status

v0.4 — the core loop (review → gate → verify), the loop driver, account pools, the multi-step workflow engine, and GitHub PR integration are complete, unit-tested, and live-verified against real providers. On the roadmap: a hosted dashboard with team policies and history, notifications, reviewer calibration stats, and more provider adapters. See [ROADMAP.md](ROADMAP.md).

## Honest limits

- **Diff-only review can false-positive** when correctness depends on code outside the hunk (helpers, state semantics). The verification round — builder rebuttal with quoted evidence, reviewers must agree — is the designed correction, and full-file context modes are on the roadmap.
- **Reviewers are models.** They miss things and occasionally invent them. The deterministic layer and your tests are not optional extras; they are half the gate.
- **A degraded review is labeled, never hidden.** If a provider is down, the report says so; `--strict` turns degradation into INCONCLUSIVE instead of a pass.

## License

MIT — see [LICENSE](LICENSE).
