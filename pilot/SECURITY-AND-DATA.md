# CodeReview pilot — security and data handling

Plain language, no marketing. Where a protection has limits, the
limits are stated. The full sandbox threat model shipped with
the product is `THREAT-MODEL.md` at the repository root; this
page is the short version for pilot participants.

## What leaves your machine

Exactly one thing: **the diff under review, plus the context the
run is configured to include** (for example file sections shown
to a reviewer for a cited finding, your `--context` text, and any
repository instructions the product ingests — see below).

It goes only to **the providers you configured, under your own
API keys**. You pick the providers in `codereview setup`; per
run you can override them. CodeReview has no account system, no
telemetry, and no server of ours in the path — the CLI on your
machine calls the providers you chose, directly.

Your keys:

- Keys come from **environment variables only** (e.g.
  `GEMINI_API_KEY`). They are never typed into the setup wizard,
  never echoed, and never stored — the config file at
  `~/.config/codereview/config.toml` references env var *names*
  only.
- Keys are not passed to reviewer agent processes or to evidence
  / test subprocesses: those run with an allow-listed environment
  (PATH, locale, proxy basics) that deliberately excludes them.

## Redaction — what it does, and its limits

Before a diff is sent to any provider, it passes through the
product's redactor (`redact_secrets`), which replaces
secret-shaped values:

- values assigned to names like `api_key`, `secret`, `password`,
  `token`, `private_key` (quoted values of 6+ characters);
- AWS access key IDs (`AKIA…`);
- `-----BEGIN … PRIVATE KEY-----` headers;
- `Bearer …` tokens of 16+ characters.

The same redaction is applied to repository instructions before
sending, to intake reports and context, and to stored evidence
output (only a redacted tail is ever stored).

**Honest limits:**

- Redaction is **pattern-based**. It covers the known key/token
  shapes above; a secret in a novel format, or a value that
  doesn't look like a secret, can pass through. Do not rely on
  redaction as your only line of defence — review what a diff
  contains before you send it to a cloud provider, exactly as
  you would before pasting it into any external tool.
- Once a (redacted) diff reaches a cloud provider, **that
  provider's terms govern it** — retention, training use, and
  sub-processors are the provider's policies, not ours. This is
  why the product has a `--private` flag: it refuses seats
  tagged with a free tier, because free tiers may train on
  submitted code.
- If a diff **must not leave the machine at all**, use local
  seats (next section) — don't bridge or cloud-review it.

## The no-egress option: local model seats

Local model servers are first-class seats: the `ollama` preset
(`http://localhost:11434/v1`) and the `lmstudio` preset
(`http://localhost:1234/v1`), or any local endpoint via
`local:<name>:<base-url>|<model>`. They are keyless, and the
review traffic goes to a loopback address on your own machine —
nothing leaves it. Local seats carry the family tag `local`
(two local seats are one family, not two independent ones — the
record says so).

## Records stay local

Every run writes its report + verdict record to
`codereview-out/` on your machine. Nothing is uploaded anywhere
by the product. If you share a record with us for pilot support,
that is your choice and your action. A record contains the
findings, evidence quotes from your diff, the panel composition,
and hashes — it does **not** contain your API keys (they are
never in the record), and evidence output stored with it is
redacted and tail-capped.

## Reviewers are read-only

- Model reviewer seats receive a prompt and return **structured
  findings only** (a JSON verdict). The review path gives them
  no tools and no write access to your tree.
- Agent seats (a local agent CLI seated as a reviewer) run the
  command *you* configured, in a fresh scratch directory
  containing only the prompt file, with an allow-listed
  environment (your provider keys are not passed). The process
  group is killed when the call ends. **Limit, stated plainly:**
  the seated agent itself runs with its own permissions —
  CodeReview cannot govern what a tool-enabled agent chooses to
  read on its own. Seat only agents you would trust at your
  keyboard, and keep their tools restricted (the shipped example
  wrapper runs the agent with all tools disabled; a reviewer
  seat needs none).
- The deterministic layer and the gate are code in the product,
  not model output: findings are merged by deterministic rules,
  and the PASS / BLOCKED / INCONCLUSIVE decision is computed,
  never voted on by a model.

## The code under review is untrusted data

- The diff, and repository instructions such as `AGENTS.md`, are
  treated as **untrusted data**. Reviewers are instructed to
  ignore instructions embedded in code and comments.
  Repository instructions are ingested (size-capped, redacted,
  delimited as untrusted data, with provenance recorded) and can
  *inform* findings — they **cannot** change the panel, the
  policy, or the gate. A `## Code Review Rules` section is
  surfaced as advisory only.
- Commands that execute code from the reviewed tree (evidence
  commands, builder-claim re-runs, lifecycle hooks) run in the
  product's sandbox: a throwaway copy of the tree (`.git`
  excluded, deleted afterwards), an allow-listed environment
  with no keys, no network by default, wall-clock / CPU /
  per-file-size limits, and captured output stored as a hash
  plus a redacted tail. The record states which isolation
  actually applied.
- **Sandbox limits, plainly:** it is confinement against
  accidents and casual hostility, **not a jail**. There is no
  filesystem isolation (sandboxed code shares your filesystem
  view via absolute paths) and memory is deliberately uncapped.
  For a genuinely hostile tree, run the whole CLI inside a VM
  or a container. `--test-command` and workflow builder/test
  commands are operator-supplied shell strings run in your
  checkout with your environment — the trust level of a CI
  config you wrote; the sandboxed evidence path is the confined
  one. Full detail: `THREAT-MODEL.md`.

## What we ask of pilots

- Run it on real changes, behind your own keys and judgement.
- If you send us a record or a feedback form, that's the data
  we see — nothing else reaches us.
- Found a way the redactor, the sandbox, or the record's honesty
  fails? That is the most valuable feedback a pilot can give;
  tell us first, before anyone else.
