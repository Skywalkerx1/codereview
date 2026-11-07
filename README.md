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

Fetches the PR's metadata + unified diff from the GitHub API and reviews it in place. Read-only works without a token on public repos. `--post` (needs `GITHUB_TOKEN` with repo access) posts the report as a PR review comment — COMMENT by default; `--request-changes` escalates a blocked gate to REQUEST_CHANGES; the bot never auto-approves — and sets a `codereview` commit status on the PR head (success / failure / pending — `pending` is the inconclusive gate: the review reached no verdict, and the status description says so explicitly rather than leaving a silent wait). Re-run with `--verify-previous report.json` after a push to run the verification round against the new diff.

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

The loop's surface is deliberately narrower than the gate command's (P6-08): it takes `--provider` (or the environment / your saved setup), `--range`/`--staged` for the diff it starts from, `--waive`, `--test-command`, `--allow-major` and `--strict` — and no `--seat-meta`, `--policy` or `--role`, because it drives its own rounds against the working tree as the builder edits it; the policy-driven surfaces (tiering, hooks, gate profile, role assignment) belong to the gate command. For the same reason its per-round records are *working* records: they carry no committed range/head, so they are not Form B chain records and cannot be release-eligible through `record-verify`. For a release record, run the gate command over a committed range.

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

### First run — you set up your models

CodeReview ships **no default panel**: we don't choose the LLM for you. On first open, run:

```bash
codereview setup
```

The wizard walks you through it: pick one or more providers, see which environment variable must hold **your** key for each (keys are never typed into, echoed by, or stored in the config — it references env var names only), then assign a model per role (correctness, operations, verifier, tech-lead, solver), confirming each one. Your choices are saved to `~/.config/codereview/config.toml` (XDG; override with `$CODEREVIEW_CONFIG`) as *your* defaults, and every later run uses them — explicit `--provider`/`--role` flags and `$CODEREVIEW_PROVIDERS` still win per run. Re-run `codereview setup` any time to change them. With no setup and no flags, a run stops and tells you how to set up — it never quietly substitutes a vendor-chosen panel. (An interactive first review launches the wizard for you.)

The model names in the table below are the registry's *suggestions* — what the wizard offers for you to confirm or replace — not decisions the product makes.

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

Keys come from environment variables only — bring your own key for every provider; nothing is stored or logged. Secrets in the diff are redacted before anything is sent to a provider: the redaction is pattern-based best-effort, covering known token formats (cloud and provider API keys, private-key blocks, credential-bearing URLs, and keyword-named assignments) — it is not a guarantee, and encoded forms of a key (base64, hex, split across lines) are not caught. The diff is treated as untrusted data — reviewers are instructed to ignore instructions embedded in code and comments.

### Pick the model for each role

Reviewing isn't one job, and one model doesn't have to do all of it. `--role <role>=<provider-spec>` assigns a provider/model per role; the role's seat joins the panel, and the assignment (seat, provider, model, vendor family) is written into the run record. Roles: `correctness` and `operations` (the two review lenses — the assigned seat serves that lens), `verifier` (the verification-round panel), `tech-lead` (the dispute adjudicator), and `solver` (intake mode's plan writer, via `codereview intake --role solver=...`). Roles you assign in `codereview setup` are your standing defaults; `--role` on a run overrides them per role for that run.

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

## Evidence runner — tests and scanners, executed and hashed

Reviewers judge a diff; they cannot run anything. The evidence runner is the deterministic counterpart: it executes your configured commands (tests, lint, SAST) and security adapters against the change and stores a hashed evidence record in the run JSON.

```bash
# Attach evidence to a review:
codereview --repo . --range main...HEAD --provider gemini \
    --provider nvidia --evidence-config evidence.json

# Or run evidence standalone:
codereview evidence --repo . --config evidence.json
# Verify the commands a builder's report claims were run:
codereview evidence --repo . --claims builder-report.md
```

The config (see `examples/evidence.json`) lists `commands` (run in order; required unless marked optional), `adapters` (`gitleaks`, `semgrep`, `dependency-audit` — each skipped cleanly as `unavailable` when its tool is not installed, never a crash), and a `require` list of names policy demands be present — a required name with no configured item is recorded as `missing`. The shape deliberately matches the policy file's `[evidence]` table, so a TOML policy's evidence section drops in unchanged.

**Gate rule.** Required evidence that fails, times out, errors, or is missing **blocks** the gate. Required evidence that is merely *unavailable* (tool not installed) makes the run **inconclusive** — the machine could not produce the evidence, which is not the builder's failure. Optional evidence is recorded and never moves the gate.

**Builder-claim verification.** Reports routinely say "ran the tests — passed". The claims mode extracts the claimed commands a work report actually commits to (a backtick-quoted command with an outcome on the same line, or a `Tests:`/`Ran:`/`Command:` line with its outcome in the tail), re-runs each one in the sandbox, and compares: a claim the re-run contradicts is recorded as **downgraded**, with both the claimed and actual outcomes. Commands mentioned without a claimed outcome are not claims and are ignored, never guessed at.

**Sandbox (the threat model in one paragraph).** Evidence commands execute code from the tree under review — untrusted code — so they run confined: in a throwaway copy of the tree (`.git` excluded, deleted afterwards, so a hostile command cannot rewrite the checkout you are about to merge), with an allow-listed environment — your provider API keys, tokens, and SSH agent **never** reach an evidence process, and HOME/TMPDIR point inside the sandbox so credential files are unreachable through them; with no network by default (proxy variables stripped, and a Linux network namespace where `unshare` is available — the record states which isolation actually applied, and an item must opt in with `"allow_network": true` to run unrestricted). One boundary on the "never reach" claim: it is the namespace mode that enforces it — in the `env-only` fallback (no `unshare`), a sandboxed command running as your uid can read the environment of other same-user processes (your shell, IDE, other agents) via `/proc/<pid>/environ`, so keys another process holds are reachable there; the run warns and records the exposure when that is live, and `env-only` is not suitable for untrusted trees (THREAT-MODEL residual 7); and under resource limits (wall-clock timeout enforced by killing the process group, CPU and per-file-size rlimits, and a per-stream cap on captured output). Every item's record carries its exit code, duration, and the sha256 of its output; only a redacted tail is stored, so a scanner that prints the secret it found cannot smuggle it into the record. Commands and adapter choices come from you (the config you point the CLI at), never from the diff. The full threat model — every control, the trust boundaries, and the residual risks (no filesystem isolation; memory deliberately uncapped) stated plainly — is `THREAT-MODEL.md` at the repository root.

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

## Dispositions and the open-dispute inventory

A refutation is not a bug to be solved: it is a dispute to be
dispositioned. Until a human ruling exists, a finding whose
refutation is `disputed` or `refutation_weak` stays open. The
tooling here makes that state computable instead of
hand-maintained (the inventory used to be re-derived by reading
every record by hand, repeatedly).

    codereview disputes [--repo DIR] [--store PATH] [--json]
    codereview disputes --record entry.json [--store PATH]
    codereview disputes --check --span A..B [--inventory FILE]

- **Computed inventory.** `codereview disputes` scans every
  `review-*/` record (JSON plus evidence sidecars), collects the
  findings whose dispute is not closed in the disposition store,
  and prints them grouped by record with fingerprints, severity,
  lens, raiser/refuter families, and the authority-affecting tag
  below. `--json` emits the same inventory for tooling. Run
  summaries also carry an `open_disputes` count and fingerprint
  list, so a finished review names what it leaves open.
- **Append-only store.** `dispositions.jsonl` at the repository
  root holds one JSON entry per dispositioned finding — nothing
  is edited or deleted. An entry carries the finding
  fingerprint; a `type` (`sustain_refutation`, `sustain_finding`,
  `split`, `fixed` — which requires the fixing `commit` —
  `retired_archived_subject`, `retired_out_of_scope`,
  `superseded`, `downgraded`); the `decider` (`owner`,
  `tech_lead`, or `probe`); a `date`; and the reasoning-quality
  fields `reason_check` (`verified` / `unverified` /
  `contradicted`), `reason_corrected`, and `basis_evidence`
  (sha256 hashes of the evidence the reasoning was checked
  against) — a ruling whose mechanism was wrong is a good
  outcome and a bad precedent, so the record keeps both. A
  fingerprint can be dispositioned only once, unless the new
  entry is marked `override` and names the `supersedes` hash of
  the entry it replaces; `codereview disputes --record` validates
  all of this on append.
- **Verification consults the store.** `record-verify`
  automatically loads `dispositions.jsonl` from the repository
  root (or `--dispositions PATH`): a disputed finding with a
  store entry counts as dispositioned, and the verdict names the
  entries consumed. When no store exists, verification behaves
  exactly as it always has.
- **Freshness check (the release-flow gate).** Before a release
  is cut, run `codereview disputes --check --span <base>..<head>`.
  It exits non-zero and lists every dispute ID in records
  touching the span that is neither dispositioned in the store
  nor present in a caller-supplied inventory file
  (`--inventory inv.json`, e.g. a fresh `disputes --json`
  snapshot): the release's dispute state is either ruled,
  listed, or the release waits. The check is a command plus this
  documentation — it is deliberately not wired into any
  automated release script.

### Authority-affecting findings

The older "protected class" is now defined deterministically. A
finding is **authority-affecting** if it could change:

- **who decides** — role/seat assignment, the Tech Lead, or the
  adjudication path;
- **whether independence holds** — family attribution;
- **whether a precedent or decision is valid** — precedent keys,
  the decision cache, verdict records as subjects;
- **whether eligibility passes** — coverage, quorum, finder
  confirmation, record-verify, gate logic;
- **what leaves the machine** — redaction, tier policy,
  `--private`, public record surfaces.

Explicitly **not** authority-affecting: report rendering and
prompt display truncation (storage is full-text; the public view
is display-only). The tagger applies this definition over a
finding's title, category, and file path; a manual override list
(`{"authority": [...], "not_authority": [...]}` JSON) always
wins. The disputes inventory prints the tag and the dimensions
matched, so a tag is auditable rather than asserted.

### Quote anchoring and `locate`

Reviewers cite line numbers in two numberings — new-side blob
lines and diff-relative indices — and nothing used to say which.
Findings now carry `line_basis` (`blob` or `diff`) whenever the
cited line and quote determine exactly one numbering;
deterministic-scan findings are always `blob`. To resolve a
citation back to the reviewed commit:

    codereview locate <finding-id> --record <record.json|dir>

`locate` takes the finding's validated quote (the evidence
sidecar's full text when the record's display copy is truncated)
and prints every blob line at the reviewed commit whose text
matches it, plus whether the cited line itself resolves. Legacy
findings without `line_basis` — or records without a head — still
locate by quote alone.

## Benchmark — prove it, don't pitch it

CodeReview's claim is measured, not asserted. The benchmark (Epic A) runs named panel configurations over a labelled corpus of diffs and scores them against ground truth:

```bash
codereview bench run --config panel-gemini-nvidia --split public
codereview bench report            # full report; --public excludes the holdout split
```

Corpus v0 ships in `bench/corpus/`: 36 cases (29 defect cases with 31 ground-truth defects, 7 clean controls; 27 public / 9 holdout), mixing authored defect injections (secrets, injection, auth regressions, payment bugs, races) with cases converted from this repo's own run records. The headline metric is the **escaped-defect rate**: defects no finding blocked on — unseen, or reported only as a minor/nit so the gate would have shipped them. Reports also carry recall, precision, clean-case BLOCKED and any-finding rates, cost per verdict, and p50/p95 latency; `bench report --max-escaped-rate R` works as a CI regression gate. Scripted replay seats (`oracle` / `blind` / `noisy` configs) run the whole harness deterministically with zero provider calls — their scores validate the harness, not any model. Definitions, corpus provenance, and the growth path to 50–100 cases live in `bench/README.md`. Anything public quotes the public split only: holdout records are dropped before scoring in `--public` reports, so no holdout case can leak into a claim.

## SARIF export — findings where your other tools live

Any saved record exports as a SARIF 2.1.0 log (Epic D, ticket D1) — the format GitHub code scanning and most static-analysis surfaces ingest:

```bash
codereview sarif review-out --out results.sarif   # or omit --out for stdout
```

The export carries the record's **open** findings: the merged findings, a verification record's still-open `remaining`, and the human-decision lists (disputed, refutation-weak, escalated), each result tagged with its adjudication state. Resolved or classified-away findings (cleared, withdrawn, fixture, precedent-standing) stay in the record, not in the alert list. Deterministic-scan findings keep their scan rule ids (`eval-exec`, …) with the scan's own descriptions; model findings group under `model-<category>` rules. Severities map blocker → `error`, major → `warning`, minor/nit → `note`; results carry the record's finding id as their fingerprint, the cited line as the region snippet, and the recommendation in the result properties. The gate and patch hash ride in the run's property bag.

## Policy: supported platforms, severity rubric, disputes

**Supported platforms.** The project supports POSIX operating systems with Python 3.11 or newer:

```toml
supported = { os = ["posix"], python = ">=3.11" }
```

A finding that depends only on an unsupported platform (for example Windows drive-letter path behaviour) is auto-labelled `out-of-scope (documented)` in the record: it stays visible in `out_of_scope_findings`, with the reason recorded, and it never blocks the gate. A finding that also claims impact on a supported platform is never labelled.

**Severity rubric.** A `blocker` or `major` requires a demonstrated, reachable defect with impact in a supported configuration, and the finding's evidence must cite the reachable path — the input, state, or call sequence that reaches the defect. Claims that cannot be traced to a reachable path, or that depend on unsupported platforms, on operator-supplied input being malicious, or on hypothetical future seat kinds, are `minor` or `nit` at most. The rubric is stated in the reviewer prompts; any label the rubric drives is recorded on the finding with its reason — severities are never silently downgraded.

**Dispute ladder and the Tech Lead.** When one vendor family refutes another family's blocking finding with quote evidence, the refutation is first graded for *adequacy*: a refutation whose quote merely repeats the line the finding itself cites carries no counter-evidence and is recorded as `refutation-weak` — a routing state, not a verdict. Every refuted finding (disputed or refutation-weak) then goes to the **Tech Lead**: a seat from a family that neither raised nor refuted the finding, which makes the *final* decision — there is no majority vote, and the project owner is the appeal, not the routine judge. The Tech Lead receives the claim, the cited code region, both positions with their quotes, and any builder-probe results, and decides one of:

- `sustain_finding` — the defect stands (the Tech Lead may *downgrade* its severity under the rubric above, never raise it);
- `sustain_refutation` — the claim is wrong and the refutation stands;
- `escalate` — the evidence is genuinely insufficient, or the panel degraded, and the case goes to the owner as an appeal/exception, with the reason recorded.

A sustain decision counts only with a quote that validates against the cited region. The Tech Lead may first send a case back for a **builder probe** (`needs_probe`) and then decide on the combined evidence; a probe can only rebut, never decide alone. The decision, the Tech Lead's family and tier, and all positions are stored on the record, and a sustained refutation or a rubric downgrade is precedent-eligible (it feeds the precedent store below). A seat can be designated for the role with `--tech-lead`; a designation whose family raised or refuted the finding is rejected and substituted — loudly, on the record, never silently accepted. When no independent Tech Lead served, the finding keeps its disputed/refutation-weak state for the human gate, and a run with such findings cannot auto-PASS.

**Precedents.** A dispositioned finding can be stored as a precedent keyed to content, not names: file-level entries hold the cited file's git blob at disposition time, and an entry may additionally key to the *enclosing function's* normalized AST hash (plus its direct callees' hashes). A function-level precedent survives unrelated edits elsewhere in the file; an edit inside the judged function — or one of its callees — re-opens the finding for fresh adjudication. When the function cannot be resolved, matching falls back to the file blob. Standing precedents are shown in the record, never hidden.

## Gate semantics

| Gate | Meaning |
|---|---|
| `PASS` | No blocking findings (blockers, and majors by default; `--allow-major` relaxes majors to advisory), and no finding waiting on a human-decision state |
| `BLOCKED` | A blocking finding stands — from a model reviewer, a deterministic rule, or a failing test command |
| `INCONCLUSIVE` | Reviewers unavailable, or (with `--strict`) the review was degraded/truncated — a human decides. Also the verdict when a finding is **disputed** (refuted cross-family with quote evidence) or could not be **re-grounded**: neither state auto-clears or auto-blocks; both route to the human gate |

Provider failure degrades the review (noted in the report); it never silently passes a change, and in `--strict` mode it blocks the pass.

## The verdict record — schema v1.0.0

Every surface — CLI, MCP server (`run_gate` / `get_verdict`), GitHub adapter, agent skills, the loop/workflow drivers — calls the same core, and the core emits **one versioned JSON verdict record** (`codereview-out/*.json`, next to the Markdown report). The contract is locked as **schema v1.0.0**: the definition and the stdlib-only validator live in `src/codereview/record_schema.py` (`RECORD_SCHEMA`, `validate_record`), the core validates every record at emission and again before it is written to disk, and golden records for all three verdicts live in `tests/fixtures/record_schema/`.

A v1 record carries, alongside the historical fields (the `schema: "codereview.report/1"` tag is unchanged; `schema_version: "1.0.0"` rides next to it):

- **Verdict, in both spellings:** `gate` (legacy lowercase: `pass` / `blocked` / `inconclusive`) and `verdict` (uppercase: `PASS` / `BLOCKED` / `INCONCLUSIVE`) — they must agree. **Exit/status semantics are stable:** CLI exit code **0 = PASS, 1 = BLOCKED, 2 = INCONCLUSIVE** (2 is also the code for a run that could not produce a record at all); the MCP `run_gate` payload returns the same verdict plus `exit_code`, and `get_verdict` reads the same record back.
- **MCP server threading limit:** `codereview mcp serve` handles one request at a time — a `run_gate` call runs to completion before the next frame is read, so a `notifications/cancelled` sent mid-run cannot interrupt it; the notification is read only after the run finishes. Long runs should be sized with the client's own timeout in mind.
- **What PASS means — and does not.** The record's `verdict_semantics` section states it in the record itself: a PASS means *no actionable issue was found under the checks that ran*. It is **not a correctness guarantee**.
- **Checks that did not run are visible:** `checks` lists every check in exactly one of `run` / `not_run` / `unavailable` (attempted, but produced no result — e.g. every reviewer seat errored). A PASS over a partial check set reads as one.
- **Findings with evidence:** each finding carries its severity, category, file/line, evidence quote, and (when stamped) its `evidence_class` — E0 deterministic, E2 probe-confirmed, E1 corroborated, E3 single-source. Absent means unstamped, never silently E0.
- **Panel composition and health:** `panel` lists each seat (provider, lens, vendor family, tier, status), the distinct families, and the degraded state; `degraded` + `degraded_causes` on the record say *why* a run degraded. Degraded-provider behaviour is never substituted silently — fallbacks are recorded per seat as before.
- **Scope, provenance, identity:** `scope` (files, patch hash, git `range`/`head` when the caller recorded them), `provenance` (generator + product version + patch hash), and `record_identity` — a content-hash `id` stamped at emission, plus the record's file name stamped by the writer (the full path travels outside the record, e.g. as the MCP payload's `record_path`).
- **Cost and duration:** `duration_ms` is the core's wall clock for the round. `cost` is explicit rather than absent: `{"status": "not_available", ...}` — core providers return review text only and report no usage to the core, so the core invents no figure. (The benchmark wrapper estimates cost from its own seat prices, outside this record, under its separate `codereview.benchresult/1` schema.)
- **Waivers:** `waivers` lists the waivers the caller recorded for the round, verbatim.

Known, documented gaps (in the schema, not hidden): the **verification round** recomputes no per-file coverage and collects no evidence/policy sections — its record lists `coverage` / `evidence` / `policy` under `checks.not_run`, and its `waivers` is always empty (verification waivers live in the loop/workflow state). The **loop summary** record (`mode: "loop"`) is a container of verdict records, not itself a v1 verdict record. Records written before v1.0.0 carry the legacy tag without `schema_version` — they are legacy records, not corrupt ones, and `record-verify`'s eligibility checks (a separate concern from schema validation) judge them by the standard of their era.

## Gate profiles

The gate's admission rule for blocking findings is a **profile**: set it per project in `.codereview.toml` (`[gate] profile`) or per run with `--gate-profile` (the flag wins over the file; the file wins over the default). Every record names the effective profile and where it came from in its `gate_profile` section.

- **`strict`** — the default, and the historical behaviour: every blocking-severity finding blocks, whoever raised it. Stated plainly: on our registered benchmark the default gate blocks most clean changes (32 of 34 clean cases under `strict`); it favours recall over precision. Use a waiver, or the opt-in `corroborated` profile below, if that trade-off is unworkable for a change.
- **`balanced`** — policy **B1** (per-lens corroboration): a blocking finding whose merged sources are *solely the operations lens* is demoted to a visible minor unless a correctness-lens seat or the deterministic layer also reported the same defect — the gate's merge is the live grouping for "same defect". Demote, never delete: the finding stays in the record with its demotion and reason (`profile_demotion`), and correctness-lens and deterministic findings are never gated by the rule. Every merged finding also carries evidence-class metadata — E0 (deterministic source), E1 (corroborated across distinct families), E3 (single-source, unverified); E2 (probe-confirmed) is assigned only when a probe result already rides on the finding, because probes run later, in adjudication. The classes are metadata only under `strict` and `balanced`: they change no verdict except through B1.
- **`corroborated`** — policy **B2** (evidence-class blocking, all lenses; opt-in and **unconfirmed — dev evidence only**): a blocking finding may block only with evidence class E0, E2, or E1. A single-source (E3) major is sent to a seat of another vendor family for confirmation with a validated deciding quote: confirmed promotes it to E1, refuted demotes it, and anything else leaves it a visible, counted, non-blocking **unverified major**. A blocking model finding must also carry a validated quote and a concrete `trigger` (the input, state, or call sequence that makes the code misbehave); missing or vague caps it at minor. If the corroborating family is unavailable the run is marked degraded. The profile requires at least two distinct vendor families able to serve the correctness lens — single-family and single-seat setups keep `strict`. B2 runs with its own versioned reviewer prompt (intent-relative review, severity calibration examples, the `trigger` field); the prompt version and hash ride in the record's `gate_profile` section, alongside the evidence-class counts and confirmation outcomes.
- **`quiet`** — *not shipped, by decision.* The original design's third profile (blanket corroboration for every lens) was tested by replay and rejected: it demoted three real single-seat majors (a destructive health-check delete, an SSRF fetch with no timeout, an unbounded response body). Naming it — on the command line, in a policy file, or in the API — is an error.

Where B1 comes from, stated as replay rather than as a live result: in the step-4 replay over the stored baseline run (public split; exploration happened on that split only), B1 held blocking recall at 29/34 on the adjudication-enlarged ground truth (24/24 on the originally labelled defects), reached merged blocking precision 1.000 excluding unknowns (0.967 including them), and cut clean-case BLOCKED from 2/5 to 1/5. Live grouping is the merge identity, not the replay's adjudicated semantic grouping, so live behaviour sits between `strict` and that row. Baseline v2's registered confirmation (2026-11-05, attempt 1) then measured B1 live: precision 0.875 and recall 7/7 on the defect stratum, but clean-case BLOCKED 22/34 — B1 was **not** confirmed, and the default stays `strict`. The follow-up is policy B2 above, developed on the consumed sets as dev data and headed for a fresh registered confirmation. The baseline and its required caveat: bench/BASELINE-2026-11-04.md.

## Project policy — `.codereview.toml`

A repository can carry its own review contract in `.codereview.toml` at its root (the review command discovers it there; `--policy PATH` overrides). The policy is the *project's* rules — distinct from your per-user setup, which only chooses your models. The gate enforces it on every review, and the record lists every rule that applied and every violation found. A blocking violation turns a PASS into BLOCKED; an `advisory` path-rule violation is recorded only.

**Discovered-policy trust.** A policy the command *discovers* in the repository under review comes from the tree itself, so it is honoured only where it can strengthen a review: panel minimums, evidence requirements, path `require_*` rules, strict waiver terms. Its `[hooks]`, a weaker-than-`strict` gate profile, `advisory` path rules, waiver leniency, `[diversity]` degrade/exclusion and `[risk]` tiering are ignored — dropped to defaults before the run, named in the record's `policy.ignored_keys`, and counted in a stderr warning. To honour a repository's policy in full, pass `--trust-repo-policy`; a policy you name yourself with `--policy` is always honoured in full.

```toml
[panel]
min_seats = 2                    # successful seats required
min_families = 2                 # distinct vendor families required
required_families = ["google"]   # families that must serve
require_lenses = ["correctness", "operations"]

[evidence]
require_tests_pass = true        # tests must run and pass

[gate]
profile = "strict"               # gate profile: "strict",
                                 # "balanced" (policy B1) or
                                 # "corroborated" (policy B2 —
                                 # see Gate profiles above)

[[paths]]                        # extra rules for sensitive paths
match = "auth/**"
require_full_panel = true        # every configured seat must serve
require_tests_pass = true

[waivers]
require_reason = true            # a waiver must say why
max_age_days = 30                # ... and it expires
```

**Lifecycle hooks.** A `[hooks]` table may declare shell commands (`pre_run`, `post_verdict`, `on_blocked`) that fire around a run. Every hook receives the event name and the record path in the `CODEREVIEW_HOOK_EVENT` / `CODEREVIEW_HOOK_RECORD` environment variables. The values are also the positional parameters `$1` / `$2` *of the hook command string itself*: a command written as a shell string — `"/path/hook.sh \"$1\" \"$2\""` — forwards them to the script, while a bare script path (`"/path/hook.sh"`) is run with no arguments and must read the environment variables instead. Hooks run sandboxed, are recorded in the record's `hooks` section, and can never change the verdict.

Every key is optional; omitted keys take the defaults (no requirement). An invalid file stops the run with a line-referenced error — a broken policy is never silently ignored. Check a file and see the effective policy with defaults filled in:

```console
$ codereview policy check
```

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
