# Response to External Review 3 of v0.4.1 — Minor fixed in v0.4.2

Reviewer verdict: **Approve with one minor follow-up.** The
v0.4.0 Major was confirmed addressed; thank you for checking the
fix paths as carefully as the original code.

## The finding

> [Minor] If the staged diff differs from the approved diff, the
> workflow runs `git reset -q -- .`, resetting the index for the
> whole repository. For a resumed workflow this can unstage
> changes that were staged before the final commit attempt. File
> contents remain, but staged state is lost.

**Verified.** We reproduced it before fixing: a resumed step
whose work (`step.py`) was pre-staged, with the staged-mismatch
branch forced — after the (correct) refusal, `git diff --cached`
was empty: the pre-staged entry was gone. Minor is the right
severity: the branch is a narrow race guard and no content could
be lost, but the state destruction was real and unnecessary.

## The fix (v0.4.2) — the reviewer's first suggestion

The approval commit is now assembled in a **temporary Git
index** (`GIT_INDEX_FILE`):

1. `read-tree <step base>` into the temporary index;
2. `add -A` the working tree (workflow output dir excluded);
3. verify the staged diff against the base is byte-identical to
   the approved diff — mismatch returns a refusal and the
   temporary index is simply discarded;
4. `write-tree` + `commit-tree` (parent = step base);
5. HEAD is moved with `update-ref HEAD <new> <base>`, guarded so
   a HEAD that moved during the attempt also refuses;
6. on success only, the real index is synced to the new HEAD —
   exactly the state a normal `git commit` leaves behind.

The user's real index is never staged into and never reset on
any refusal path, so the recovery the reviewer flagged no longer
exists — there is nothing to recover.

## Regression tests (suite: 44, all passing)

- `test_mismatch_refusal_preserves_staged_index` — the reviewer's
  suggested test: a resumed step with pre-staged work, a forced
  staged mismatch, and assertions that HEAD is unchanged and the
  pre-staged entry is still staged after the refusal.
- `test_approval_commit_contains_exactly_step_files` now also
  asserts the post-commit index is clean (temp-index sync leaves
  no residue).
- Both earlier reproductions were re-run against v0.4.2: the
  v0.4.0 dirty-tree case still refuses with the user's edits
  untouched, and the v0.4.1 index case now shows the staged entry
  preserved (`step.py` still staged after the refusal, previously
  empty).
