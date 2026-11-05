---
name: codereview
description: "Run the CodeReview multi-model review gate on a workspace and report its verdict honestly. Use when the user asks for a CodeReview run, a review gate, or whether a change passes review before shipping. Requires the `codereview` CLI (pip package `codereview-ai`) with a saved provider setup."
---

# CodeReview

CodeReview runs a panel of independent models over a change,
adjudicates their findings, and lets a deterministic gate —
not any single model — decide. The gate has exactly three
verdicts: **PASS**, **BLOCKED**, and **INCONCLUSIVE**. Your job
is to run the gate and report what it decided, citing the run
record. The record is the verdict; your summary is not.

## Before you run

Check the CLI exists:

```bash
command -v codereview
```

If it is missing, stop and tell the user to install it
(`pip install codereview-ai`) and run `codereview setup` once
to choose their reviewer panel. Never invent a review, a
verdict, or findings when the gate did not run.

This works anywhere — a plain terminal, or inside a herdr
pane (the herdr plugin's "review current workspace" action
runs the same command). herdr pane state is not the verdict;
only the record is.

## Run the gate

From the repository root:

```bash
codereview --repo .
```

With no range flags this reviews the working tree against
`HEAD` — staged, unstaged, and untracked changes. Variants:

```bash
codereview --repo . --staged          # only the index
codereview --repo . --range main...HEAD
codereview --patch change.diff        # a patch file instead
```

Expect the run to take a while: several models review
independently, then findings are verified. Do not interrupt
it or run it twice hoping for a friendlier panel.

Exit codes mirror the verdict: `0` = PASS, `1` = BLOCKED,
`2` = INCONCLUSIVE or a setup/infrastructure error.

## Read the record

The run prints its record paths at the end:

```text
codereview: gate = BLOCKED (<reasons>)
  findings: 3 (1 blocking-severity)
  report: codereview-out/codereview-<timestamp>.md
  data:   codereview-out/codereview-<timestamp>.json
```

- Records live in the output directory (default
  `codereview-out/` in the reviewed repo), one timestamped
  `.json` + `.md` pair per run.
- The **JSON record is the source of truth**: `gate`,
  `gate_reasons`, `findings` (each with a stable `id`,
  `severity`, file/line, and the reviewers behind it),
  `reviewer_reports` (per-seat status, fallbacks, seat
  state), and `degraded` when the panel did not run at full
  strength.
- Read the record before reporting. If the summary you are
  about to give disagrees with the record, the record wins.

## Report the verdict honestly

- **PASS** — say the gate passed. Mention the finding count
  and any non-blocking findings worth the user's attention.
- **BLOCKED** — never soften it. Do not call a blocked change
  "basically fine", "passing with warnings", or "approved
  pending fixes". Report each blocking finding with its
  record `id` and file/line, and the gate's stated reasons.
  Fixing code and re-running is a new run with a new record —
  report the new verdict, and say that it is a new run.
- **INCONCLUSIVE** — say the gate could not decide, and why
  (the record says: a seat failed, the panel degraded, a
  quota/auth wall). INCONCLUSIVE is not a pass and not a
  block; never report it as either. If a fallback seat served
  or the panel degraded, say so — the user is entitled to
  know the verdict came from a reduced panel.
- **Never claim a verdict the record doesn't carry.** Quote
  the gate value from the record (`pass` / `blocked` /
  `inconclusive`), cite the record path, and cite findings
  by their record ids. If you did not run the gate in this
  session, say that plainly instead of summarising someone
  else's run as your own.

## Follow-up rounds

When the builder answers a blocked round, run the
verification round against the previous record instead of a
fresh review:

```bash
codereview --repo . --verify-previous codereview-out/<record>.json \
    --builder-response @response.md
```

To check whether a saved record is eligible to stand as a
release record (clean gate, full panel, current range):

```bash
codereview record-verify codereview-out/<record>.json --repo .
```

## Do not

- Do not edit the code under review to make findings
  disappear, suppress findings, or re-run the gate repeatedly
  and report only the best outcome — unless the user
  explicitly asks you to fix the findings, in which case each
  fix gets its own new run and record.
- Do not treat a single reviewer's opinion (including your
  own reading of the diff) as the gate's verdict.
- Do not report exit code 2 as "an error in the code": it
  means the *gate* could not decide or could not run.
