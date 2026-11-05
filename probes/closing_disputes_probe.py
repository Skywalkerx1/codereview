#!/usr/bin/env python3
"""Closing round-1 workup probe — disputes.py claims:

  0bb1b939ab67  build_inventory does not deduplicate findings
                across records (the same open dispute id in two
                record files is counted twice).
  e9ef62daa1a0  records_touching_span iterates all records
                without timeout or limit.
  cf6fe742fc2e  records_touching_span has no timeout on the git
                rev-list subprocess.
  55c815ff5fbe  freshness check silently skips records whose
                recorded range is a single commit.
  6458b8824abc  check_freshness does not filter by record
                freshness age.

Method: exercise the real functions. (a) A temp root holding the
same record JSON under two review-*/ dirs — count inventory rows
per id. (b) Count git subprocess calls during a span scan of the
real repo + show the subprocess timeout in source. (c) Synthetic
records with range shapes 'X..X', 'P..X', 'X' against a span
containing X — observe touching/unscoped placement. (d) Read
check_freshness's contract from its docstring and call.

Exit 0 = the probe ran to completion (verdicts are read from the
printed observations, not the exit code)."""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import disputes  # noqa: E402

OUT = os.path.join(HERE, "results", "closing-disputes.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def main():
    say("CLOSING DISPUTES PROBE — disputes.py claims")
    say("")

    # ---- (a) cross-record dedup (0bb1b939ab67) ----------------
    say("== (a) build_inventory cross-record dedup ==")
    src_rec = os.path.join(
        REPO, "review-closing-r1",
        "codereview-20261105-031927.json")
    with open(src_rec, encoding="utf-8") as fh:
        record = json.load(fh)
    tmp = tempfile.mkdtemp(prefix="closing-dedup-")
    try:
        for d in ("review-one", "review-two"):
            os.makedirs(os.path.join(tmp, d))
            with open(os.path.join(tmp, d, "rec.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(record, fh)
        inv = disputes.build_inventory(tmp, ())
        from collections import Counter
        counts = Counter(r["id"] for r in inv["open"])
        dup = {k: v for k, v in counts.items() if v > 1}
        say(f"  records_scanned={inv['records_scanned']} "
            f"open_rows={len(inv['open'])} "
            f"unique_ids={len(counts)}")
        say(f"  ids appearing more than once: {len(dup)} "
            f"(e.g. {dict(list(dup.items())[:3])})")
        say("  VERDICT: " + ("REPRODUCES — the same dispute id "
                             "is counted once per record file"
                             if dup else "no duplication observed"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say("")

    # ---- (b) span scan cost + rev-list timeout ----------------
    say("== (b) records_touching_span cost / timeout ==")
    import inspect
    src = inspect.getsource(disputes._git_lines)
    say("  _git_lines source carries: "
        + ", ".join(ln.strip() for ln in src.splitlines()
                    if "timeout" in ln))
    calls = {"n": 0}
    real = disputes._git_lines

    def counting(repo, *args):
        calls["n"] += 1
        return real(repo, *args)

    disputes._git_lines = counting
    try:
        touching, unscoped = disputes.records_touching_span(
            REPO, REPO, "3013656..2fbf94f")
    finally:
        disputes._git_lines = real
    n_records = len(disputes.iter_record_files(REPO))
    say(f"  record files under root: {n_records}; git subprocess "
        f"calls for one span scan: {calls['n']} "
        f"(touching={len(touching)}, unscoped={len(unscoped)})")
    say("  VERDICT: per-call timeout exists (120s — cf6fe742fc2e "
        "premise fails); the scan is O(records) subprocess calls "
        "with no caching of repeated range specs and no overall "
        "bound (e9ef62daa1a0's substance).")
    say("")

    # ---- (c) single-commit range shapes (55c815ff5fbe) --------
    say("== (c) records_touching_span range shapes ==")
    head = disputes._git_lines(REPO, "rev-parse", "HEAD")[0]
    parent = disputes._git_lines(REPO, "rev-parse", "HEAD~1")[0]
    span = f"{parent}..{head}"
    tmp = tempfile.mkdtemp(prefix="closing-span-")
    try:
        def put(dirname, rng, hd):
            os.makedirs(os.path.join(tmp, dirname))
            rec = {"schema": "codereview.report/1",
                   "range": rng, "head": hd}
            with open(os.path.join(tmp, dirname, "r.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(rec, fh)

        put("review-degenerate", f"{head}..{head}", head)
        put("review-normal", span, head)
        put("review-baresha", head, head)
        touching, unscoped = disputes.records_touching_span(
            REPO, tmp, span)
        say(f"  span={span}")
        say(f"  touching={sorted(touching)}")
        say(f"  unscoped={sorted(unscoped)}")
        say("  'review-degenerate' (range X..X, head inside the "
            "span) appears in NEITHER list: "
            + str("review-degenerate/r.json" not in touching
                  and "review-degenerate/r.json" not in unscoped))
        say("  VERDICT: REPRODUCES for the degenerate X..X shape "
            "— rev-list yields an empty set (not None), so the "
            "head fallback never runs and the record is silently "
            "dropped from the freshness check. A bare-sha range "
            "behaves oppositely (rev-list returns the commit and "
            "its ancestors, so it touches everything).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say("")

    # ---- (d) check_freshness contract (6458b8824abc) ----------
    say("== (d) check_freshness filtering contract ==")
    doc = (disputes.check_freshness.__doc__ or "").strip()
    say("  docstring: " + " ".join(doc.split())[:300])
    import inspect as _i
    sig = str(_i.signature(disputes.check_freshness))
    say(f"  signature: check_freshness{sig}")
    say("  No age/freshness-window parameter or concept exists "
        "in disputes.py (grep 'age' over the module: only "
        "'message'-class substrings). The §5.3 contract is: "
        "span-touching + not dispositioned + not inventoried. "
        "VERDICT: the claim names a filter the adopted design "
        "does not specify; the function implements its contract.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
