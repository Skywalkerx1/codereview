# CodeReview

**One agent builds. Independent models review. A deterministic gate decides.**

CodeReview is a multi-model code review loop for teams where AI agents write a growing share of the code. A single model reviewing its own work rubber-stamps it; a human reviewing everything becomes the bottleneck. CodeReview puts the change in front of *other* models — with different providers, different lenses — and lets code, not vibes, decide whether it ships.

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
- **Alerts about the loop itself can't flood you** — the same dedup discipline CodeReview checks for in your code is part of its own design brief (see the `alert-no-guard` rule, born from a real incident: an hourly checker that emailed on every run while the same violation persisted for weeks).

## Quick start

```bash
pip install codereview-ai        # or: pip install -e . from a clone

export GEMINI_API_KEY=...     # any two providers are a good start
export OPENAI_API_KEY=...

# Review the staged diff in the current repo
codereview --repo . --staged --provider gemini --provider openai

# Review a patch file, with your test suite as a first-class input
codereview --patch change.diff \
  --provider gemini --provider xai \
  --test-command "python -m pytest -q" \
  --context "Adds retry logic to the payment webhook handler"

echo $?   # 0 = PASS, 1 = BLOCKED, 2 = INCONCLUSIVE
```

The report lands in `codereview-out/` as Markdown (for humans) + JSON (for tooling).

## Intake — from issue report to solution plan

Everything above starts from a code change that already exists. Intake starts from the problem:

```bash
codereview intake issue-report.md \
  --provider gemini --provider nvidia \
  --context src/alerts.py --repo .
```

Solver models (a separate seat type that answers in Markdown, not JSON) read the issue report plus any context files and the repo's file listing, and each writes a solution plan in a fixed shape: diagnosis steps in order, ranked hypotheses — each with the test that settles it — a numbered fix plan, prevention, risks and rollback, and closure criteria a verifier can run. The first solver that answers becomes `solution.md`; the others are kept as alternates next to it, with an `intake.json` manifest recording the report's hash, what was sent, and every truncation. Reports and context are secret-redacted and size-capped before anything leaves the machine.

Intake writes no code and gates nothing: the builder reads `solution.md`, implements it, and the review loop above gates the resulting change. Exit 0 means a plan was produced; exit 2 means every solver failed.

## Account pools — when a free quota dies, the next account reviews

Repeat a seat to give it several accounts:

```bash
export GEMINI_API_KEY=...        # account 1
export GEMINI_API_KEY_2=...      # account 2
codereview --repo . --provider gemini --provider gemini --provider nvidia
```

Accounts are tried in order; a quota, rate-limit, 5xx, or dead-key error rotates the seat to the next account. Every report records **which account served and each rotation** (from → to → error) — fallback is visible in the run history, never silently substituted. If every account fails, the seat degrades honestly and the gate says so. Custom specs sharing a name pool the same way (one account per spec, labelled by its key env).

## Multi-step workflows

```bash
codereview workflow --file workflow.json --repo . --out wf-out
```

`workflow.json`: `{"steps": [{"id": "db", "title": "Add the schema", "agent_cmd": "…", "test_commands": ["…"]}]}`. Steps run in order; each step's change goes through the full review loop; on PASS the change is **committed as the step's approval record** and the workflow advances to the next step. State persists in `wf-out/workflow-state.json` — rerun to resume (approved steps are skipped), touch `wf-out/STOP` to pause between steps, and record owner waivers under the state's `waivers` map (`{step_id: [finding_id, …]}`).

**Working-tree isolation:** a step that is starting fresh requires a **clean working tree** — commit or stash local edits first; the engine stops with a clear message rather than reviewing or committing changes that are not the step's. (A resumed step keeps its own in-progress changes.) The approval commit is verified byte-for-byte against the diff the reviewers approved; if the tree changed after the final review round, the commit is refused. The commit itself is assembled in a **temporary Git index**, so a refusal never alters your real index — staged work you had before the run is exactly where you left it.

## GitHub pull requests

```bash
codereview pr --repo OWNER/REPO --number 123                 # read-only review
codereview pr --pr https://github.com/OWNER/REPO/pull/123 --post
```

Fetches the PR's metadata + unified diff from the GitHub API and reviews it in place. Read-only works without a token on public repos. `--post` (needs `GITHUB_TOKEN` with repo access) posts the report as a PR review comment — COMMENT by default; `--request-changes` escalates a blocked gate to REQUEST_CHANGES; the bot never auto-approves — and sets a `codereview` commit status on the PR head (success / failure / pending). Re-run with `--verify-previous report.json` after a push to run the verification round against the new diff.

## The loop driver — the full workflow in one command

```bash
codereview loop --repo . \
    --builder-cmd "your-coding-agent-command" \
    --provider gemini --provider nvidia --max-rounds 3
```

1. Reviewers review the working-tree diff. **PASS → the workflow advances** (exit 0).
2. On BLOCKED, the findings are written to `$CODEREVIEW_PACKET` (JSON) and your builder command — the coding agent — is invoked. It edits the working tree and writes its **work report** (per finding: what changed, with test evidence) to `$CODEREVIEW_RESPONSE`.
3. A verification round checks the fixes against the new diff. PASS advances; BLOCKED loops back to the builder.
4. After `--max-rounds` builder rounds without a PASS, the loop stops and hands back to a human. A round that cannot complete (reviewer outage) stops the loop as INCONCLUSIVE — infrastructure problems are never blamed on the builder.

Per-round reports land in `round-1/`, `round-2/`, … and `loop-result.json` summarizes the run (`advanced: true/false`).

## The verification round

A blocked change is fixed — or rebutted with evidence — and re-checked:

```bash
codereview --patch fix.diff \
  --verify-previous codereview-out/codereview-20261103-150000.json \
  --builder-response @response.md \
  --provider gemini --provider openai
```

A prior blocker clears **only when every successful reviewer agrees** it is fixed (with evidence in the new diff) or was invalid. A split verdict keeps the block. The builder can never approve their own work — that rule is the product.

## Providers

Any two (or more) independent models, from any major vendor. Presets (each is also usable as `preset:model` to pick a specific model):

| Preset | Default model | Your key in |
|---|---|---|
| `openai` | gpt-5-mini | `OPENAI_API_KEY` |
| `gemini` | gemini-2.5-flash | `GEMINI_API_KEY` |
| `anthropic` | claude-sonnet-4-5 | `ANTHROPIC_API_KEY` |
| `deepseek` | deepseek-chat | `DEEPSEEK_API_KEY` |
| `minimax` | MiniMax-M2 | `MINIMAX_API_KEY` |
| `moonshot` | kimi-k2-0711-preview | `MOONSHOT_API_KEY` |
| `nvidia` | nvidia/nemotron-3.5-lightning-30b-a3b | `NVIDIA_API_KEY` |
| `xai` | grok-4-mini | `XAI_API_KEY` |
| `mistral` | mistral-large-latest | `MISTRAL_API_KEY` |
| `openrouter` | anthropic/claude-sonnet-4.5 | `OPENROUTER_API_KEY` |

Any other OpenAI-compatible endpoint works too, either fully custom:

```
--provider "mine|openai-compatible|https://api.example.com/v1|model-id|MY_KEY_ENV"
```

or via the generic escape hatch `--provider "openai-compatible:https://api.example.com/v1|model-id|MY_KEY_ENV"`. (Anthropic's native Messages API and Gemini's native API are wired directly; everything else rides the OpenAI-compatible shape most vendors now expose.)

Keys come from environment variables only — bring your own key for every provider; nothing is stored or logged. Secrets in the diff are redacted before anything is sent to a provider, and the diff is treated as untrusted data — reviewers are instructed to ignore instructions embedded in code and comments.

### Pick the model for each role

Reviewing isn't one job, and one model doesn't have to do all of it. `--role <role>=<provider-spec>` assigns a provider/model per role; the role's seat joins the panel, and the assignment (seat, provider, model, vendor family) is written into the run record. Roles: `correctness` and `operations` (the two review lenses — the assigned seat serves that lens), `verifier` (the verification-round panel), `tech-lead` (the dispute adjudicator), and `solver` (intake mode's plan writer, via `codereview intake --role solver=...`). With no `--role`, behaviour is exactly as before.

```bash
# Strong models on the lenses, a cheap high-volume model as Tech Lead:
codereview --repo . \
  --provider anthropic --provider openai \
  --role tech-lead=deepseek:deepseek-reasoner

# Kimi on correctness, MiniMax on operations:
codereview --repo . \
  --role correctness=moonshot --role operations=minimax
```

Cost guidance: the Tech Lead and other high-volume seats are called once per dispute or round, so they are the natural home for the inexpensive, high-quality seats — DeepSeek, MiniMax, and Moonshot (Kimi) are first-class presets for exactly this. One independence rule is enforced by the record: each seat carries its vendor *family* from the registry (a seat built from `moonshot` is family `moonshot` whatever you name it), and the Tech Lead's family must differ from the families that raised and refuted a finding — pick the Tech Lead from a different vendor than your two reviewers.

### Agent seats — any agent as a reviewer

A panel seat doesn't have to be a model API. Any local agent CLI can review (or solve), riding on the subscription you already have for it — no vendor API key involved:

```bash
codereview --repo . \
  --provider gemini \
  --provider "agent:claude:sh examples/agent-seat-claude.sh" \
  --provider "agent:grok:<your grok bot command>"
```

The contract is the one the builder already uses: the prompt (diff + instructions) is written to a file named by `$CODEREVIEW_PROMPT` and piped to the command's stdin; whatever the agent prints on stdout is its verdict. Claude Code, Codex, Gemini CLI, a Grok bot, or your own wrapper script all fit the same seat. The command line is split like a shell line (POSIX rules) and run **without a shell** — metacharacters are literal, so anything needing pipes or redirection goes in a wrapper script (as in the example). Repeating an agent name creates distinct seats (`claude`, `claude-2`, ...), because each spec is a different agent, not another account of one seat; an agent seat may not share a name with an API seat — that configuration is rejected loudly rather than merged. A seat that exits non-zero, times out (900s for reviewers, the intake deadline for solvers), or prints nothing is recorded as failed in the report — degraded honestly, never silently replaced. Agent commands are operator-supplied configuration, like `--builder-cmd`; they are never read from the repo or the diff under review.

**The agent-seat boundary, plainly.** CodeReview runs each agent in a fresh scratch directory containing only the prompt file, with an allow-listed environment: your provider API keys are **not** passed to agent processes (only PATH/HOME/locale/proxy basics, plus any names you opt in via `CODEREVIEW_AGENT_ENV`). The seat's process group is killed when the call ends — timeout or not — and on POSIX its file writes are capped at 8 MB per file (on Windows only the direct child is killed). A seat that doesn't need login state in HOME can shed that exposure too: `agent:claude[home=private]:...` points HOME at the scratch directory. What CodeReview cannot do is govern the agent itself: a seated agent runs with **its own permissions**, and the redaction guarantee covers the prompt CodeReview sends — not files the agent chooses to read on its own. Seat only agents you would trust at your keyboard, keep their tools restricted (the example wrapper runs Claude Code with `--tools ""` — the brief is self-contained, so a reviewer seat needs no tools at all), and remember that the diff under review is untrusted input to a tool-enabled process.

## Release records — preflight, fallbacks, verification

A gate verdict you intend to *publish* (a release record) has to survive its own panel being flaky. Three mechanisms keep that honest:

- **Preflight.** `codereview doctor [--provider ...] [--fallback lens=spec]` probes every seat — primaries and fallbacks — with the *exact review request shape* (a toy probe can lie: a JSON-mode provider may reject a non-review-shaped request the real review would never send) and prints per-seat health as JSON with an error class — a dead quota or a missing key shows up *before* a run, not inside a wasted record.
- **Fallback seats.** Provider failures are classified (daily quota and auth errors are never retried; per-minute rate limits and 5xx/overloads get bounded backoff — every attempt is recorded). If a lens's primary seat still fails, a configured fallback serves it: `--fallback correctness=openai`. The substitution is printed on the report and in the gate reasons, never silent.
- **Machine-checked eligibility.** Every reviewer report records its seat's vendor **family** and pricing **tier** (`--seat-meta gemini:google:paid`). `codereview record-verify <record-dir> --repo .` then decides whether a record may be called clean: gate PASS, not degraded, tests passed, every lens served, at least two distinct vendor families, the reviewed range's patch hash unchanged, and no later commits except the one filing the record. Relatedly, `--private` refuses seats tagged with a free tier — free tiers may train on submitted code, so they don't review private repositories.
- **Fixture scope, declared and machine-checked.** Deliberately-buggy test *data* (a benchmark corpus, scripted seats' canned responses) is not product code, but silently skipping it would be worse than reviewing it. Instead, a versioned **fixture manifest** (`fixtures-manifest.json`: every fixture path, why it is intentionally vulnerable, expected finding categories, a policy version) can be declared with `--fixture-manifest`. The review still runs over the full patch; findings belonging to declared fixture data are classified in the record as **expected fixture findings** — evidence and counts preserved — and do not block the gate. The record carries the manifest's path, content hash, policy version, and classified paths, and `record-verify` recomputes all of it against the manifest committed at the recorded head: a missing, stale, or mismatched manifest fails verification. Ordinary reviews without a declared scope scan fixtures exactly like product code. A manifest entry may also declare an `expected_finding_count`: findings on that path *beyond* the count are not classified — they stay in the record as product findings, with the excess noted.
- **Coverage accounting (v0.9.3).** Every review record carries, per file and per lens, which batches covered it — derived from the actual batching the run used. `record-verify`'s `coverage_complete` check fails a record whose own accounting shows a file/lens omission (a run with omissions is also marked degraded at review time); records that predate coverage accounting report the check as not applicable rather than failing retroactively.
- **Evidence-grounded findings (v0.9.3).** A model finding must carry an `evidence_quote` copied exactly from the diff text its reviewer received; the quote is validated deterministically against that batch. A finding that fails validation is not dropped: it goes through an automatic **re-ground pass** — the raising seat (or another family's) is shown the exact file section and must confirm with a valid quote or withdraw. Confirmed findings stand (marked re-grounded), withdrawn findings stay in the record as `withdrawn_findings` with the seat's reason, and a finding no seat could re-ground stays visible and makes the gate INCONCLUSIVE — a human decides it.
- **Cross-family confirmation (v0.9.3).** A blocker/major raised by a single vendor family is put to a seat of a *different* family that served the run, with the cited file's section as evidence. Agreement leaves it blocking. A refutation counts only with a quote that validates against that section; a refuted finding becomes **disputed**: it leaves the blocking set, is listed in `disputed_findings`, and the gate may not auto-PASS — the verdict is INCONCLUSIVE and the human gate decides. A refutation without a valid quote changes nothing.
- **Round-structured records — Form B (v0.9.3).** A release record may also be a *chain*: one complete-coverage full review, then verification rounds over the fix diffs. `codereview record-verify --chain <round-1-dir> <verify-dir> [...] --repo .` checks the whole chain: ranges contiguous from base to HEAD with patch hashes recomputed, every round non-degraded with two families, round 1's coverage complete, every round-1 blocker/major cleared on the record by a verification round, final gate PASS with tests passing and the final head current. The adopted convergence budget (at most 3 verification rounds, non-increasing new-blocker counts) is reported as WARN lines — a process flag for the owner — not as an eligibility failure.
- **Tier attestation (v0.9.3).** Records carry the run's own `private` declaration (from `--private`) alongside each seat's tier. `record-verify`'s `tier_policy` check fails exactly one conjunction: a `private=true` record with a *successful* free-tier seat. Public runs attest `private=false` and are unaffected; records without a declaration report the check as not applicable.
- **Content-addressed precedent (v0.9.3).** Re-litigating a settled rebuttal every round wastes the panel; trusting prose dispositions would let a builder talk the gate down. The middle path is a **precedent store** (`precedents.json`, passed with `--precedents`): each entry keys a finding fingerprint + cited path to the cited file's git blob at disposition time. A matching finding is classified **standing** — listed in `standing_findings` with its repeat count and disposition link, non-blocking — *only while that file's blob is unchanged*; any edit retires the precedent automatically and the finding is adjudicated fresh. `record-verify` recomputes the store hash and every link against the recorded head, so a stale or forged link fails.

## Benchmark — prove it, don't pitch it

CodeReview's claim is measured, not asserted. The benchmark (Epic A) runs named panel configurations over a labelled corpus of diffs and scores them against ground truth:

```bash
codereview bench run --config panel-gemini-nvidia --split public
codereview bench report            # full report; --public excludes the holdout split
```

Corpus v0 ships in `bench/corpus/`: 36 cases (29 defect cases with 31 ground-truth defects, 7 clean controls; 27 public / 9 holdout), mixing authored defect injections (secrets, injection, auth regressions, payment bugs, races) with cases converted from this repo's own run records. The headline metric is the **escaped-defect rate**: defects no finding blocked on — unseen, or reported only as a minor/nit so the gate would have shipped them. Reports also carry recall, precision, clean-case false-positive rate, cost per verdict, and p50/p95 latency; `bench report --max-escaped-rate R` works as a CI regression gate. Scripted replay seats (`oracle` / `blind` / `noisy` configs) run the whole harness deterministically with zero provider calls — their scores validate the harness, not any model. Definitions, corpus provenance, and the growth path to 50–100 cases live in `bench/README.md`. Anything public quotes the public split only: holdout records are dropped before scoring in `--public` reports, so no holdout case can leak into a claim.

## Gate semantics

| Gate | Meaning |
|---|---|
| `PASS` | No blocking findings (blockers, and majors by default; `--allow-major` relaxes majors to advisory), and no finding waiting on a human-decision state |
| `BLOCKED` | A blocking finding stands — from a model reviewer, a deterministic rule, or a failing test command |
| `INCONCLUSIVE` | Reviewers unavailable, or (with `--strict`) the review was degraded/truncated — a human decides. Also the verdict when a finding is **disputed** (refuted cross-family with quote evidence) or could not be **re-grounded**: neither state auto-clears or auto-blocks; both route to the human gate |

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
