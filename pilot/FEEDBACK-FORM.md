# CodeReview pilot — feedback form

Thank you for running the pilot. This form is the pilot: the
product is early, and your answers here shape it more than any
benchmark we run ourselves. Fill it in after your demo run and
after at least one run on a real change of your own. Type over
the dotted lines, tick the boxes, delete what doesn't apply.

Pilot name / handle (optional): …………………………………………
Date: ………………………  CodeReview version (`codereview --version` or the record's `version` field): ………………………

---

## 1. What PASS means — in your own words

We state it in every record as: *"no actionable issue was found
under the checks that ran"* — and explicitly **not** a
correctness guarantee.

1a. In your own words, what does a PASS from CodeReview mean?

> ………………………………………………………………………………………………
> ………………………………………………………………………………………………

1b. And what does a PASS **not** mean? Name at least one thing a
PASS does not rule out.

> ………………………………………………………………………………………………
> ………………………………………………………………………………………………

1c. Did anything in the report or record make PASS sound
stronger than that? If so, quote it:

> ………………………………………………………………………………………………

## 2. Setup friction log

For each step where something slowed you down, confused you, or
failed — one row per incident. Add rows as needed.

| # | Step (install / `codereview setup` / demo / first real run) | What happened | Time it took |
|---|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |

Total time from starting the install to your first completed
review: ………………………

## 3. Findings — accepted or rejected, one by one

For each finding from your runs (attach or name the record file
so we can find it: …………………………………………):

| Finding (record file + finding `id` or title) | Accepted / Rejected | Why — was it real? reachable? worth fixing? |
|---|---|---|
|  |  |  |
|  |  |  |
|  |  |  |
|  |  |  |

Also: did the panel **miss** anything you know was in a change
you ran? Describe it — a miss you caught yourself is the most
useful row in this form.

> ………………………………………………………………………………………………
> ………………………………………………………………………………………………

## 4. Checks that did not run

Every record lists `checks.run` / `checks.not_run` /
`checks.unavailable`.

4a. In your runs, which checks did not run (look at a record —
e.g. `tests` when no `--test-command` was passed)?

> ………………………………………………………………………………………………

4b. Before reading that list, had you assumed those checks
*had* run?  ☐ Yes  ☐ No

4c. Does the distinction between `not_run` and `unavailable`
(attempted, but produced no result) make sense as presented?
What would you rename or re-explain?

> ………………………………………………………………………………………………

## 5. Repeat use

5a. Would you run CodeReview on your next real change?
☐ Yes  ☐ No  ☐ Only for some kinds of change (which?): ………………………

5b. Did you actually run it on a real change beyond the demo?
☐ Yes — how many changes so far: ………
☐ No — what stopped you: ………………………………………………………

5c. What almost stopped you from running it the second time?

> ………………………………………………………………………………………………

## 6. What would it be worth?

6a. If CodeReview worked the way you now expect it to, what
would it be worth to you?
Per month: ………………………  — or per review: ………………………
☐ Nothing — I would not pay for this. (That's a useful answer.)

6b. What would make it a clear **yes** at that price?

> ………………………………………………………………………………………………

6c. What would make it a clear **no** at any price?

> ………………………………………………………………………………………………

## 7. One founder question

What is the last real failure you shipped — a bug or bad change
that reached users — and how did you find out about it?

> ………………………………………………………………………………………………
> ………………………………………………………………………………………………
> ………………………………………………………………………………………………

Would CodeReview, as you have seen it behave, have had a chance
of catching it?  ☐ Yes  ☐ No  ☐ Can't tell — why: ………………………

## 8. Consent (all default to NO)

We will not quote, name, or publish anything of yours without
the matching box ticked.

☐ You may **quote** my words from this form (anonymously unless
   the next box is also ticked).
☐ You may **name** me / my project alongside a quote.
☐ You may **publish my run record(s)** (the JSON/Markdown I
   send you) — I understand a record contains findings and
   quoted lines from my diff.

Anything else you want us to know:

> ………………………………………………………………………………………………
> ………………………………………………………………………………………………
