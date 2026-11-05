#!/usr/bin/env python3
"""Oversize probe — open-refutations solution §3, for
6219e04d4c00 (bucket A #1): "Unplaceable oversized piece is
appended to a fresh batch without any size guard."

Probe (§3): craft one section whose smallest placeable piece
exceeds the budget (its diff head alone meets/exceeds the
budget, so _split_section must return it whole, unplaceable);
assert (1) the batching flags it incomplete — the guard the
claim says does not exist; (2) a full run over it is degraded
with the coverage-incompleteness stated in the gate reasons —
the loud path, not a silent send; (3) record, as evidence, the
size of what is actually sent (the design sends the section
whole rather than truncating content silently — the flag and
the degraded marking are the guard; nothing about the send is
silent).

Contrast case: a placeable oversized section (small head, long
body) at the same machinery — every batch within budget, no
content lost, incomplete NOT set.

Exit 0 = the guard assertions held."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

BUDGET = 40

# A section whose HEAD (diff --git / --- / +++ lines) alone is
# longer than the budget: _split_section cannot frame even a
# minimal slice, so it returns the section whole + unplaceable.
HEAD = ("diff --git a/some/deeply/nested/module/path/app.py "
        "b/some/deeply/nested/module/path/app.py\n"
        "--- a/some/deeply/nested/module/path/app.py\n"
        "+++ b/some/deeply/nested/module/path/app.py\n")
SECTION = HEAD + "@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"

# Placeable contrast: small head, long body lines.
SMALL_HEAD = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
LONG_SECTION = (
    SMALL_HEAD + "@@ -1,3 +1,3 @@\n"
    + "".join(f"+line {i:03d} " + "y" * 60 + "\n" for i in range(30)))


def ok_verdict(prompt):
    return json.dumps({"verdict": "pass", "summary": "ok",
                       "findings": []})


def main():
    lines = [
        "OVERSIZE PROBE — 6219e04d4c00",
        "Claim: an unplaceable oversized piece 'is appended to",
        "a fresh batch without any size guard'.",
        "",
        f"Budget (max_chars): {BUDGET}",
        f"Crafted section: head = {len(HEAD)} chars "
        f"(>= budget), total = {len(SECTION)} chars",
        "",
    ]
    pieces, unplaceable = core._split_section(SECTION, BUDGET)
    lines.append(f"_split_section -> {len(pieces)} piece(s), "
                 f"unplaceable={unplaceable}")
    assert unplaceable is True, "fixture must be unplaceable"

    batches, batch_files, incomplete = \
        core._batch_sections_detailed([("app.py", SECTION)], BUDGET)
    lines.append(f"_batch_sections_detailed -> batches="
                 f"{[len(b) for b in batches]}, incomplete={incomplete}")
    assert incomplete is True, "the guard flag must be set"
    lines.append("ASSERTION 1 HELD: batching flags the unplaceable"
                 " section incomplete — the size guard exists and"
                 " fires (the flag is what the claim denies).")

    prompts = []

    def recorder(prompt):
        prompts.append(prompt)
        return ok_verdict(prompt)

    patch = ("diff --git a/some/deeply/nested/module/path/app.py "
             "b/some/deeply/nested/module/path/app.py\n"
             "--- a/some/deeply/nested/module/path/app.py\n"
             "+++ b/some/deeply/nested/module/path/app.py\n"
             "@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n")
    report = core.run_review(
        patch, {"seatA": recorder, "seatB": recorder},
        max_patch_chars=BUDGET, sleep=lambda *a: None)
    lines += [
        "",
        f"run_review over the section (budget {BUDGET}):",
        f"  truncated (batching incomplete) = {report['truncated']}",
        f"  coverage.complete = {report['coverage']['complete']}",
        f"  degraded = {report['degraded']}",
        f"  gate = {report['gate']}",
        f"  first gate reason: {report['gate_reasons'][0]!r}",
        f"  provider calls made: {len(prompts)}; the section text"
        f" was sent in {sum(1 for p in prompts if 'x = 2' in p)}"
        " of them",
    ]
    assert report["truncated"] is True
    assert report["coverage"]["complete"] is False
    assert report["degraded"] is True
    assert any("could not be placed within the batch budget" in r
               for r in report["gate_reasons"])
    lines.append("ASSERTION 2 HELD: the run is degraded, coverage"
                 " is recorded incomplete, and the gate reasons"
                 " state the cause in plain text — the loud path.")
    lines += [
        "",
        "EVIDENCE (recorded, not asserted away): the batch that",
        f"carries the unplaceable section is {len(batches[0])}"
        " chars — larger than the budget. The design sends the",
        "section WHOLE rather than truncating content, and pays",
        "for it with the incomplete flag + degraded run + stated",
        "reason above. Nothing is silent; no content is cut.",
        "",
        "CONTRAST — placeable oversized section (small head,"
        " 30 long body lines) at budget 400:",
    ]
    batches2, _files2, incomplete2 = core._batch_sections_detailed(
        [("b.py", LONG_SECTION)], 400)
    joined = "".join(batches2)
    lines += [
        f"  batches={[len(b) for b in batches2]}, "
        f"incomplete={incomplete2}",
        f"  every batch <= 400: {all(len(b) <= 400 for b in batches2)}",
        f"  all body content present across batches: "
        f"{all(f'line {i:03d}' in joined for i in range(30))}",
    ]
    assert incomplete2 is False
    assert all(len(b) <= 400 for b in batches2)
    lines += [
        "",
        "PROBE OUTCOME: both guard assertions held. The claim's",
        "mechanism — 'without any size guard' — is rebutted: the",
        "guard is the unplaceable flag, which forces incomplete",
        "coverage and a degraded, reason-stating run. Supports",
        "the pre-filled recommendation: sustain refutation",
        "('designed loud path'), owner ratifies (authority-",
        "affecting: coverage accounting).",
    ]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, "oversize-6219e04d4c00.txt"),
              "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
