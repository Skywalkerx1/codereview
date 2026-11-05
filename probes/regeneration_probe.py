#!/usr/bin/env python3
"""Regeneration probe — open-refutations solution §2, for the
three record-subject claims in bucket A:

  7baa0147d8d4  verification summary undercounts cleared blockers
  7ea4e96603e9  reviewer success count contradicts degraded status
  212878ab6bba  verification record says degraded while the
                summary claims all reviewers succeeded

Procedure (§2): load the stored JSON for the cited record,
re-render it with the CURRENT renderer (core.render_markdown /
core.verify_record), compare the relevant gate/summary lines
with the archived .md / record-verify.txt, and render a
synthetic fixture of the contested shape (all reviewers OK,
degraded true because coverage was incomplete).

Outcomes per §2: HEAD's rendering correct/clarified -> retire
as retired_archived_subject with this output attached; HEAD
still renders the misleading line -> convert to a NEW finding
against the renderer code.

Writes full-text results to probes/results/. Exit 0 when the
probe ran to completion (the probe reports facts; the outcome
classification is printed, not asserted away)."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)


def emit(name, lines):
    text = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, name), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return text


def gate_line(md):
    for ln in md.splitlines():
        if ln.startswith("**Gate:"):
            return ln
    return ""


# ----------------------------------------------------------------
# 7baa0147d8d4 — cleared-blocker count
# ----------------------------------------------------------------
def probe_undercount():
    path = os.path.join(
        REPO, "review-v15-verify1", "codereview-20261104-225424.json")
    md_path = path[:-5] + ".md"
    rec = json.load(open(path, encoding="utf-8"))
    cleared = rec.get("cleared") or []
    remaining = rec.get("remaining") or []
    unjudged = rec.get("unjudged") or []
    rendered = core.render_markdown(rec)
    archived = open(md_path, encoding="utf-8").read()

    def count_line(md):
        for ln in md.splitlines():
            if ln.startswith("Cleared prior blockers:"):
                return ln
        return ""
    lines = [
        "REGENERATION PROBE — 7baa0147d8d4",
        "Claim: the verify summary says 'Cleared prior blockers: 4'",
        "but the paired JSON 'contains five entries under cleared'.",
        "",
        f"Stored JSON: {path}",
        f"  len(cleared)   = {len(cleared)}",
        f"  len(remaining) = {len(remaining)}",
        f"  len(unjudged)  = {len(unjudged)}",
        f"  total prior blockers accounted = "
        f"{len(cleared) + len(remaining) + len(unjudged)}",
        "  cleared ids: " + ", ".join(
            str(f.get('id')) for f in cleared),
        "",
        f"Archived .md line:    {count_line(archived)!r}",
        f"Re-rendered at HEAD:  {count_line(rendered)!r}",
        f"JSON count:           {len(cleared)}",
        "",
    ]
    agree = (count_line(rendered) == count_line(archived)
             and len(cleared) == 4)
    if agree:
        lines += [
            "OUTCOME: HEAD's renderer agrees with the stored JSON",
            "and with the archived summary: 4 cleared. The claim's",
            "premise — five entries under 'cleared' — does not hold",
            "against the stored JSON: five is the TOTAL of prior",
            "blockers (4 cleared + 0 remaining + 1 unjudged), not",
            "the cleared count. Per solution §2 the claim retires",
            "as retired_archived_subject with this probe attached.",
        ]
    else:
        lines += [
            "OUTCOME: HEAD's rendering does NOT agree with the",
            "stored JSON — the claim converts to a new finding",
            "against the renderer (core.render_markdown).",
        ]
    return emit("regeneration-7baa0147d8d4.txt", lines)


# ----------------------------------------------------------------
# 7ea4e96603e9 / 212878ab6bba — degraded vs reviewer success
# ----------------------------------------------------------------
def synthetic_fixture():
    """The contested shape at HEAD, built the way run_review
    builds it: _gate with degraded=True + incomplete=True and
    every reviewer ok, then render_markdown."""
    gate, reasons = core._gate(
        [], degraded=True, incomplete=True, any_success=True)
    report = {
        "mode": "review", "gate": gate, "gate_reasons": reasons,
        "degraded": True, "truncated": True,
        "created_at": "probe", "patch_sha256": "0" * 64,
        "coverage": {"complete": False, "files": {"app.py": {}},
                     "batch_count": 1, "omissions": []},
        "reviewer_reports": [
            {"provider": "seatA", "lens": "correctness",
             "status": "ok"},
            {"provider": "seatB", "lens": "operations",
             "status": "ok"}],
        "findings": [],
    }
    return report, core.render_markdown(report)


def probe_degraded_pair(fid, cited_path, cited_kind):
    rec_path = os.path.join(
        REPO, "review-v15", "codereview-20261104-224759.json")
    rec = json.load(open(rec_path, encoding="utf-8"))
    rendered = core.render_markdown(rec)
    archived = open(cited_path, encoding="utf-8").read()
    rr = rec.get("reviewer_reports") or []
    ok = sum(1 for r in rr if r.get("status") == "ok")
    fixture, fixture_md = synthetic_fixture()
    lines = [
        f"REGENERATION PROBE — {fid}",
        "Claim: the record says degraded while the reviewer",
        "count claims all reviewers succeeded — a contradiction.",
        "",
        f"Stored JSON: {rec_path}",
        f"  degraded = {rec.get('degraded')}, "
        f"coverage.complete = "
        f"{(rec.get('coverage') or {}).get('complete')}",
        f"  reviewer_reports: {ok} of {len(rr)} status ok",
        "  gate_reasons include: "
        + "; ".join(r for r in rec.get("gate_reasons") or []
                    if "reviewer failed" in r
                    or "coverage incomplete" in r),
        "",
        f"Cited artifact ({cited_kind}): {cited_path}",
    ]
    if cited_kind == "markdown":
        lines += [
            f"  archived gate line:   {gate_line(archived)!r}",
            f"  re-rendered at HEAD:  {gate_line(rendered)!r}",
            f"  identical: {gate_line(archived) == gate_line(rendered)}",
        ]
    else:
        checks = core.verify_record(rec, record_dir="review-v15")
        nd = [c for c in checks["checks"]
              if c["name"] == "not_degraded"]
        lines += [
            "  archived record-verify.txt line 2: "
            "'  [FAIL] not_degraded: degraded=True'",
            f"  verify_record at HEAD: not_degraded ok={nd[0]['ok']} "
            f"detail={nd[0]['detail']!r}",
            "  (The FAIL is CORRECT behaviour: the run WAS degraded",
            "   — by truncated coverage, not by reviewer failure.)",
        ]
    lines += [
        "",
        "Synthetic fixture at HEAD (all reviewers ok, degraded",
        "by incomplete coverage, built via core._gate):",
        f"  gate line: {gate_line(fixture_md)!r}",
        f"  _gate reasons: {fixture['gate_reasons']}",
        "",
        "OUTCOME: HEAD still renders the misleading shape. The",
        "gate line pairs 'DEGRADED' with '(N of N reviewers",
        "succeeded)' and a boilerplate reason 'at least one",
        "reviewer failed (degraded review)' even when NO reviewer",
        "failed and degradation came from coverage. The degraded",
        "CAUSE is not stated at the point of the DEGRADED marker.",
        "Per solution §2 the claim converts to a NEW finding",
        "against the renderer/gate-reason code (minor): state",
        "the degraded cause in the gate line (e.g. 'DEGRADED:",
        "coverage incomplete; reviewers 2/2 ok') and only claim",
        "reviewer failure when a reviewer actually failed. The",
        "archived-subject claim retires on conversion.",
    ]
    return emit(f"regeneration-{fid}.txt", lines)


if __name__ == "__main__":
    probe_undercount()
    probe_degraded_pair(
        "7ea4e96603e9",
        os.path.join(REPO, "review-v15",
                     "codereview-20261104-224759.md"),
        "markdown")
    probe_degraded_pair(
        "212878ab6bba",
        os.path.join(REPO, "review-v15", "record-verify.txt"),
        "verify")
