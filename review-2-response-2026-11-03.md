# Response to External Review 2 of v0.4.0 — fixed in v0.4.1

Reviewer verdict: **Request changes** — one Major. We verified the
finding against the code and by reproduction before fixing; it was
real in full. Thank you — this was exactly the class of bug the
project exists to catch, in the project's own commit path.

## The finding

> A passing workflow step can commit unrelated working-tree
> changes. The workflow records `HEAD` as the step base, reviews
> `git diff <base>` (which includes pre-existing staged/unstaged
> edits), and on PASS runs `git add -A`, committing everything
> except the workflow output directory. No clean-tree precondition
> or change isolation.

**Verified.** Our reproduction (repo with a committed base file,
then an unstaged edit to it plus an unrelated untracked file, then
a one-step workflow whose agent creates only `step.py`) produced
an approval commit containing `base.txt`, `unrelated.txt`, and
`step.py`, with the workflow reporting complete. The reviewer's
suggested directions — clean-tree precondition and/or staging only
the step's changes with an exactness check — are both implemented.

## The fix (v0.4.1)

1. **Clean-tree precondition for fresh steps.** Before a step's
   agent runs, the engine checks `git status` (staged, unstaged,
   and untracked; the workflow output directory excepted). Any
   pre-existing change stops the workflow: the step is recorded
   `needs_attention` with an error naming the offending paths, the
   agent never runs, and the user's edits are left untouched.
   A step that was already started (state carries `started_at` —
   e.g. a `changes_requested` step being resumed) skips the check
   and keeps its own in-progress tree, so the fix-round resume
   flow is unchanged.
2. **Exact approval commits.** On PASS the engine re-reads the
   current diff and compares its sha256 with the final reviewed
   report's `patch_sha256`; a mismatch (the tree changed after the
   reviewers saw it) refuses the commit. It then stages —
   output directory excluded — and verifies the staged diff is
   byte-identical to the approved diff before committing; a
   mismatch resets the index and stops the step as
   `needs_attention`. The approval commit therefore contains
   exactly the diff that passed the gate, nothing else.
3. **The engine no longer reviews its own output.** The workflow
   output directory is excluded from the reviewed diff and from
   intent-to-add untracked tracking (previously possible when the
   output dir sat inside the repo across fix rounds).

## Regression tests (suite: 43, all passing)

- `test_fresh_step_refuses_dirty_tree` — the reproduction above:
  workflow stops, step `needs_attention`, agent never runs, HEAD
  unchanged, the local edits remain in the tree uncommitted.
- `test_approval_commit_contains_exactly_step_files` — the
  approval commit's file set is exactly the step's files.
- `test_resumed_step_keeps_its_in_progress_tree` — a
  `changes_requested` step resumes with its uncommitted work and
  commits exactly that work on PASS.
- `test_tree_changed_after_review_refuses_commit` — a file created
  during the final review round (after the reviewed patch was
  captured) makes the commit refuse; HEAD unchanged.

The original reproduction script was also re-run against v0.4.1:
the workflow now stops with `needs_attention` and no approval
commit is created.

## What did not change

The review/gate/verification semantics, the loop driver, account
pools, and the GitHub PR integration are untouched by this fix.
The reviewer's scope note stands: they inspected source and did
not run the suite; the suite results above are ours.
