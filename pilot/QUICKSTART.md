# CodeReview pilot — quick start

You are running an early pilot of CodeReview: one agent (or human)
builds a change, independent models review it, and a deterministic
gate — not a model's opinion — decides PASS / BLOCKED /
INCONCLUSIVE and writes a versioned record of the decision.

This page takes you from nothing to your first review in about
15 minutes. The first review uses scripted stand-in reviewers, so
it works offline with no API keys. Your second review uses your
own models and keys.

## 1. Install (from source — the one-line install is coming)

The PyPI package (`pip install codereview-ai`) is **not published
yet**. For the pilot, install from the public mirror:

```bash
git clone https://gitlab.com/superstartelecom/codereview
# (the same code is mirrored at https://codeberg.org/superstartelecom/codereview)
cd codereview
pip install -e .
```

Requirements: **Python 3.11 or newer** on a POSIX system
(Linux/macOS). CodeReview itself is Python standard library only —
the install pulls in no third-party dependencies.

Check it runs:

```bash
codereview --help
```

## 2. Set up your models (`codereview setup`)

CodeReview ships **no default panel** — we don't choose the LLM
for you. Run the setup wizard once:

```bash
codereview setup
```

The wizard:

1. Offers providers (OpenAI, Gemini, Anthropic, DeepSeek,
   MiniMax, Moonshot/Kimi, NVIDIA, xAI, Mistral, OpenRouter, any
   OpenAI-compatible endpoint), local model servers (Ollama /
   LM Studio — keyless, nothing leaves your machine), and agent
   CLIs you already have installed.
2. For each API provider, tells you **which environment variable
   must hold your key** — for example `GEMINI_API_KEY`. Keys are
   never typed into the wizard, never echoed, and never stored:
   the config file references env var *names* only. Export the
   variables in your shell before running reviews:

   ```bash
   export GEMINI_API_KEY=...
   export OPENAI_API_KEY=...
   ```

3. Asks you to assign a model per **role** and confirm each one:
   `correctness` and `operations` (the two review lenses),
   `verifier` (the verification round), `tech-lead` (dispute
   adjudicator), and `solver` (plan writer for intake mode).

Your choices are saved to `~/.config/codereview/config.toml`
(override the location with `$CODEREVIEW_CONFIG`). Re-run
`codereview setup` any time to change them. Per run, explicit
`--provider` / `--role` flags and `$CODEREVIEW_PROVIDERS` still
win over the saved setup.

Any two independent models are a good start. One rule of thumb
from the product design: pick reviewers from **different vendor
families** — independence is the point.

If there is no setup and a run has no `--provider` flags, the run
**stops and explains how to set up**. It never quietly substitutes
a vendor-chosen panel.

## 3. Your first review — the demo (no keys needed)

Follow [DEMO.md](DEMO.md). It reviews two small changes to a
toy billing module using scripted stub seats: one change is
blocked for a planted payment defect, one passes. It takes about
two minutes and shows you the exact record format your real
reviews will produce.

## 4. Review your own change

From the root of *your* repository:

```bash
# Review the staged diff, using your saved setup
codereview --repo . --staged

# …or a range, with your test suite as a first-class input
codereview --repo . --range main...HEAD \
  --test-command "python -m pytest -q"

# …or a patch file
codereview --patch change.diff
```

Add `--provider gemini --provider openai` (etc.) to override the
panel for a single run.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | **PASS** |
| `1` | **BLOCKED** |
| `2` | **INCONCLUSIVE**, or the run could not produce a record (usage / infrastructure error) |

### Where records land

Every run writes two files to `codereview-out/` (override with
`--out DIR`):

- `codereview-<timestamp>.md` — the human-readable report;
- `codereview-<timestamp>.json` — the verdict record
  (schema v1.0.0, below), for tooling and for the verification
  round.

Records stay on your machine unless you choose to share them.

## 5. How to read a verdict record (schema v1.0.0)

The JSON record is the contract: every surface (CLI, MCP server,
GitHub adapter) emits the same one. The fields you will actually
use:

- `schema` — always `"codereview.report/1"`, with
  `schema_version` — `"1.0.0"` — next to it.
- `verdict` — `PASS` / `BLOCKED` / `INCONCLUSIVE` (uppercase).
  The legacy lowercase twin `gate` (`pass` / `blocked` /
  `inconclusive`) carries the same fact; the two always agree.
- `gate_reasons` — the gate's own words for why it decided as it
  did, e.g. `["1 blocking finding(s) (major)"]`.
- `findings[]` — the merged findings standing at the gate. Each
  carries `id`, `severity` (`blocker` / `major` / `minor` /
  `nit`), `category`, `file`, `line`, `title`, `evidence`,
  `evidence_quote` (the cited line, copied exactly from the
  diff and checked mechanically), `evidence_class`,
  `recommendation`, and `confidence`.
  - `evidence_class` says how much stands behind a finding:
    **E0** deterministic (a rule in the product's own scanner,
    not a model), **E1** corroborated across distinct vendor
    families, **E2** probe-backed (confirmed by an executed
    check), **E3** single-source (one seat/family, uncorroborated).
    An absent class means "unstamped", never "E0".
- `checks` — every check in exactly one of `run` / `not_run` /
  `unavailable` (attempted, but produced no result — e.g. every
  reviewer seat errored). **Checks that did not run are visible.**
  A PASS over a partial check set reads as one.
- `panel` — who reviewed: `seats[]` (provider, lens, vendor
  `family`, `tier`, `status`), `families`, `seat_count`,
  `ok_count`. `reviewer_reports` carries the per-seat detail.
- `degraded` + `degraded_causes` — `true` when something in the
  panel failed or fell back, with the causes named. A degraded
  run is labelled, never dressed up as a healthy one.
- `scope` — what was reviewed: `files`, `patch_chars`,
  `patch_sha256`, the git `range` / `head` when recorded, and
  `previous_gate` on a verification round.
- `cost` — always `{"status": "not_available", ...}`. The core
  has no cost data (providers return review text only) and
  invents none.
- `duration_ms` — the core's wall clock for the round.
- `waivers` — waivers recorded for the round, verbatim.
- `provenance` — generator, product version, patch hash.
- `record_identity` — `id` is a content hash of the record,
  stamped at emission.
- `verdict_semantics` — what the verdict means, stated in the
  record itself: a PASS means **no actionable issue was found
  under the checks that ran**. It is **not a correctness
  guarantee** — checks that did not run are listed in `checks`,
  and a degraded panel is labelled in `panel` /
  `degraded_causes`.

### Annotated excerpt (real record, from the demo in DEMO.md)

```json
{
  "schema": "codereview.report/1",
  "schema_version": "1.0.0",
  "mode": "review",
  "gate": "blocked",
  "verdict": "BLOCKED",
  "gate_reasons": ["1 blocking finding(s) (major)"],
  "findings": [
    {
      "id": "7ff7b0375451",
      "severity": "major",
      "category": "correctness",
      "file": "billing.py",
      "line": 27,
      "title": "Dollar amount passed where the gateway expects cents",
      "evidence_quote": "    return gateway.charge(amount_cents=order.total_dollars, currency=\"usd\")",
      "evidence_class": "E3",
      "recommendation": "Convert before the call: amount_cents = dollars_to_cents(order.total_dollars), and pass amount_cents to the gateway.",
      "confidence": 0.95
    }
  ],
  "checks": {
    "run": ["deterministic_scan", "reviewer_panel", "coverage"],
    "not_run": ["tests", "evidence", "policy"],
    "unavailable": []
  },
  "panel": {
    "seats": [
      {"provider": "stub-a", "lens": "correctness", "family": "agent", "tier": "unknown", "status": "ok"},
      {"provider": "stub-b", "lens": "operations", "family": "agent", "tier": "unknown", "status": "ok"}
    ],
    "families": ["agent"],
    "seat_count": 2,
    "ok_count": 2,
    "degraded": false
  },
  "degraded": false,
  "degraded_causes": [],
  "cost": {"status": "not_available", "amount_usd": null},
  "verdict_semantics": {
    "pass_means": "no actionable issue found under the checks that ran (see the checks section)",
    "pass_is_not": "not a correctness guarantee: checks that did not run are listed in checks.not_run / checks.unavailable, and a degraded panel is labelled in panel / degraded_causes"
  }
}
```

(Two fields to notice in this excerpt: `checks.not_run` includes
`tests` — the demo run passed no `--test-command`, and the record
says so rather than implying tests ran. And the finding is `E3`:
both demo seats are scripted stand-ins sharing one family,
`agent`, so nothing corroborated the finding across families.
With two real providers from different families, the same merged
finding would be stamped E1.)

## 6. Fix, then re-review — the verification round

A blocked change is not re-reviewed from scratch. Fix the code
(or rebut the finding with evidence) and run the **verification
round**, pointing at the previous record:

```bash
codereview --patch fix.diff \
  --verify-previous codereview-out/codereview-<timestamp>.json \
  --builder-response @response.md
```

- `--verify-previous <record.json>` links the new run to the
  blocked one: the new record is a fresh record (its own
  `record_identity`), and its `scope.previous_gate` carries the
  prior record's gate.
- `--builder-response` is your per-finding work report: what you
  changed, with test evidence — or why the finding was wrong,
  with quoted evidence.
- A prior blocker clears **only when every successful reviewer
  agrees** it is fixed or was invalid. A split verdict keeps the
  block. The builder can never approve their own work — that
  rule is the product.

## 7. If something goes wrong

- Run `codereview doctor` before a run to probe every seat with
  a real review-shaped request — a dead quota or a missing key
  shows up there, not inside a wasted record.
- A run that degrades says so in the report and in
  `degraded_causes`; in `--strict` mode degradation makes the
  verdict INCONCLUSIVE instead of a pass.
- Stuck? Send us the record JSON (it contains no keys — see
  [SECURITY-AND-DATA.md](SECURITY-AND-DATA.md) for exactly what
  it does and doesn't contain) plus what you typed.
