# CodeReview pilot — the demo (10 minutes, no API keys)

A deterministic walkthrough of a full gate run. You review two
small changes to a toy billing module: one is **blocked** for a
planted payment defect, one **passes**. The reviewers are
scripted stub seats — stand-ins that use CodeReview's real
agent-seat mechanism — so the run works offline, with no keys,
and produces real verdict records in the real format
(schema v1.0.0).

What this demo proves: the install, the seat mechanism, the
gate, the exit codes, and how to read a record. What it does
**not** prove: that a real model will catch this defect. That
is what the "repeat it live" section at the end is for.

## The demo project

`pilot/demo/project/` is a tiny billing module for a small
shop's checkout:

- `billing.py` — an `Order`, a `dollars_to_cents()` converter,
  and `charge_order()`, which charges through a payment gateway
  whose API expects **integer cents** ($49.99 → `4999`).
- `test_billing.py` — two unit tests, including one that checks
  `charge_order` sends cents.

The two changes (both are patches against that base):

1. **`pilot/demo/change-1-defect.patch`** — rewrites
   `charge_order` to pass `order.total_dollars` directly as
   `amount_cents`, dropping the conversion. A $49.99 order would
   be charged as 49.99 *cents-units* instead of 4999. This is
   the planted defect.
2. **`pilot/demo/change-2-clean.patch`** — adds
   `charge_order_with_retry()`: retries transient gateway
   failures, passes an explicit per-attempt timeout, and keeps
   the cents conversion. This change is correct.

## The stub seats

`pilot/demo/stub_seat.py` is a scripted seat. CodeReview's
agent-seat contract (README, "Agent seats") is: the review
prompt is written to the file named by `$CODEREVIEW_PROMPT` and
piped to the seat's stdin; the seat prints exactly one JSON
verdict object on stdout. The stub recognises the planted
defect by its exact added line and answers with a `major`
finding quoting that line; for anything else it answers
"pass". It also answers the gate's follow-up passes (re-ground,
cross-family confirmation) in their own JSON shapes.

Honest labels, because they matter for reading the records:

- The stub is **not a model** and this is **not a benchmark**.
  It always catches the planted defect, by construction.
- Both stub seats share one vendor family, `agent`. So in the
  change-1 record the merged finding is stamped evidence class
  **E3** (single-source family) with `cross_family:
  "unavailable"` — the gate had no second family to confirm it
  with. With two real providers from different families, the
  same merged finding would be stamped E1.

## Run it

Install first (see [QUICKSTART.md](QUICKSTART.md) §1), then,
**from the root of your clone**:

### Change 1 — expect BLOCKED, exit code 1

```bash
codereview --patch pilot/demo/change-1-defect.patch \
  --provider "agent:stub-a:python3 $PWD/pilot/demo/stub_seat.py" \
  --provider "agent:stub-b:python3 $PWD/pilot/demo/stub_seat.py" \
  --out pilot/demo/out-change-1-defect
echo $?
```

(The `$PWD` matters: agent seats run in a fresh scratch
directory, so the stub script is referenced by absolute path.
Your shell expands `$PWD` before CodeReview sees the argument.)

Recorded output (author's run, 2026-11-06; the author's record
files are preserved verbatim in `pilot/demo/sample-records/` —
your timestamps will differ, the verdict will not):

```
codereview: gate = BLOCKED (1 blocking finding(s) (major))
  findings: 1 (1 blocking-severity)
  report: pilot/demo/sample-records/change-1-defect/codereview-20261106-051032.md
  data:   pilot/demo/sample-records/change-1-defect/codereview-20261106-051032.json
```

Exit code: **1**.

The Markdown report's finding, verbatim:

```
- 🔶 **[major] Dollar amount passed where the gateway expects cents** (billing.py:27) — via stub-a, stub-b · consensus · evidence E3
  - evidence: `return gateway.charge(amount_cents=order.total_dollars, currency="usd")`
  - fix: Convert before the call: amount_cents = dollars_to_cents(order.total_dollars), and pass amount_cents to the gateway.
```

And the JSON record says, among the v1.0.0 fields:
`verdict: "BLOCKED"`, `gate_reasons: ["1 blocking finding(s)
(major)"]`, one finding (`id 7ff7b0375451`, `severity: "major"`,
`file: "billing.py"`, `line: 27`, `evidence_class: "E3"`, its
`evidence_quote` validated against the diff), `panel` with both
stub seats `status: "ok"`, `degraded: false`, and
`checks.not_run` including `tests` — no test command was passed
to this run, and the record says so instead of implying one
ran. The full record is at
`pilot/demo/sample-records/change-1-defect/`.

### Change 2 — expect PASS, exit code 0

```bash
codereview --patch pilot/demo/change-2-clean.patch \
  --provider "agent:stub-a:python3 $PWD/pilot/demo/stub_seat.py" \
  --provider "agent:stub-b:python3 $PWD/pilot/demo/stub_seat.py" \
  --out pilot/demo/out-change-2-clean
echo $?
```

Recorded output (author's run, 2026-11-06):

```
codereview: gate = PASS ()
  findings: 0 (0 blocking-severity)
  report: pilot/demo/sample-records/change-2-clean/codereview-20261106-051032.md
  data:   pilot/demo/sample-records/change-2-clean/codereview-20261106-051032.json
```

Exit code: **0**. The record's `verdict` is `"PASS"` with empty
`findings` — and its `verdict_semantics` still states what that
means: *no actionable issue was found under the checks that
ran*. Not a correctness guarantee.

### Sanity check you can run yourself

The demo project's own tests agree with the gate. Copy
`pilot/demo/project/` somewhere scratch, apply change 1, and
`python3 -m unittest` **fails** (the cents test); apply
change 2 instead and it passes. The demo runs above deliberately
passed no `--test-command`, so the records list `tests` under
`checks.not_run` — run a real review with
`--test-command "python -m pytest -q"` (or your suite) and the
tests become part of the gate.

## Repeat it live with your own keys

Same two changes, real models:

```bash
codereview setup        # once: pick providers, assign models per role
                        # (the wizard names the env var for each key;
                        #  export those variables in your shell)

codereview --patch pilot/demo/change-1-defect.patch \
  --provider gemini --provider openai
codereview --patch pilot/demo/change-2-clean.patch \
  --provider gemini --provider openai
```

(Substitute your providers; or drop the `--provider` flags and
your saved setup is used.) Records land in `codereview-out/` by
default.

What to expect, honestly: real models are not the stub. A model
may catch the dollars/cents defect, miss it, or raise something
else — findings are merged across your panel, quotes are
validated mechanically, and the gate decides by rule. Comparing
your live records with the stub records in
`pilot/demo/sample-records/` — same schema, different panel —
is the fastest way to see what the record format is for. And
whether the live panel catches the planted defect is exactly
the kind of signal the pilot feedback form asks about.
