#!/usr/bin/env python3
"""Unknown-family fail-closed probe — open-refutations
solution §3, for 3d9645200bc5 (bucket C #1): the claim noted
the family tag is set inside a try/except, so a failure could
leave a seat untagged; the refutation answered that an
untagged/unknown family fails every independence check closed.

Probe (§3): two custom seats pointed at the SAME vendor base
(both honestly 'unknown' family) and assert, on all three
independence surfaces, that unknown can never pass for known:

  (construction) build_providers tags both seats 'unknown'
                 even though they front the same vendor;
  (a) Tech Lead selection: an unknown-family designated seat
      is rejected with the substitution recorded, and a panel
      of only unknown seats yields NO Tech Lead;
  (b) a run whose blocking finding was raised by an
      unknown-family seat is marked cross_family =
      'unknown_family' — never multi-family, never confirmed
      away by the second unknown seat;
  (c) verify_record's two_families check FAILS on a record
      whose ok reports are all family 'unknown'.

Exit 0 = fail-closed on every surface."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core, providers  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

PATCH = ("diff --git a/app.py b/app.py\n--- a/app.py\n"
         "+++ b/app.py\n@@ -1,1 +1,2 @@\n x = 1\n"
         "+VALUE = compute_total(items)\n")
QUOTE = "VALUE = compute_total(items)"


def seat_raising(prompt):
    if "RE-GROUND" in prompt or "CONFIRMATION" in prompt:
        # An unknown-family checker must never be asked; if it
        # were, answering 'confirm' here is the worst case.
        return json.dumps({"status": "confirmed",
                           "verdict": "confirm",
                           "reason": "confirming"})
    return json.dumps({
        "verdict": "findings", "summary": "one",
        "findings": [{"severity": "major",
                      "category": "correctness", "file": "app.py",
                      "line": 2, "title": "Unguarded total",
                      "evidence": QUOTE, "evidence_quote": QUOTE,
                      "recommendation": "guard it",
                      "confidence": 0.9}]})


def seat_pass(prompt):
    return json.dumps({"verdict": "pass", "summary": "ok",
                       "findings": []})


def main():
    lines = ["UNKNOWN-FAMILY FAIL-CLOSED PROBE — 3d9645200bc5",
             ""]
    env = {"PT1_KEY_A": "k-a", "PT1_KEY_B": "k-b"}
    old = dict(os.environ)
    os.environ.update(env)
    try:
        specs = ["vendor-a|openai-compatible|"
                 "http://127.0.0.1:9/v1|model-x|PT1_KEY_A",
                 "vendor-b|openai-compatible|"
                 "http://127.0.0.1:9/v1|model-x|PT1_KEY_B"]
        descs = [providers.describe_spec(s) for s in specs]
        panel = providers.build_providers(specs)
    finally:
        os.environ.clear()
        os.environ.update(old)
    fams = {n: getattr(fn, "_codereview_family", None)
            for n, fn in panel.items()}
    lines += [
        "CONSTRUCTION: two custom seats, same vendor base",
        "http://127.0.0.1:9/v1, same model:",
        f"  describe_spec families: "
        f"{[d['family'] for d in descs]}",
        f"  built seat families:    {fams}",
    ]
    assert all(f == "unknown" for f in fams.values())
    lines.append("  -> both seats are family 'unknown': the "
                 "machinery cannot tell they share a vendor,")
    lines.append("     so independence must fail closed. It "
                 "does, on all three surfaces:")

    # (a) Tech Lead selection
    fns = {"vendor-a": seat_pass, "vendor-b": seat_pass,
           "knownseat": seat_pass}
    fam_map = {"vendor-a": "unknown", "vendor-b": "unknown",
               "knownseat": "famK"}
    name, _fn, fam, subst, unavail = core._select_tech_lead(
        fns, set(fns), fam_map, "vendor-a", "famA", "famB")
    lines += ["",
              "(a) Tech Lead, designated = unknown-family seat",
              "    (raiser/refuter known families):",
              f"    chosen = {name!r} (family {fam!r})",
              f"    substitution recorded: "
              f"{subst['reason'] if subst else None!r}"]
    assert name == "knownseat" and subst is not None
    assert "unknown" in subst["reason"]
    name_b, _fb, _famb, subst_b, _ub = core._select_tech_lead(
        fns, set(fns), fam_map, "vendor-a", "unknown", "unknown")
    lines += ["    designated unknown with raiser/refuter also",
              "    'unknown' (the claim's exact shape):",
              f"    chosen = {name_b!r}; substitution reason: "
              f"{subst_b['reason'] if subst_b else None!r}"]
    assert name_b == "knownseat" and subst_b is not None
    name2, _f2, _fam2, _s2, unavail2 = core._select_tech_lead(
        {"vendor-a": seat_pass, "vendor-b": seat_pass},
        {"vendor-a", "vendor-b"},
        {"vendor-a": "unknown", "vendor-b": "unknown"},
        None, "unknown", "unknown")
    lines += ["    panel of ONLY unknown seats: "
              f"chosen = {name2!r}, unavailable = {unavail2!r}"]
    assert name2 is None and unavail2
    lines.append("    ASSERTION HELD: unknown never adjudicates.")

    # (b) run-level cross-family treatment
    report = core.run_review(
        PATCH,
        {"vendor-a": seat_raising, "vendor-b": seat_pass},
        seat_meta={"vendor-a": {"family": "unknown"},
                   "vendor-b": {"family": "unknown"}},
        sleep=lambda *a: None)
    standing = (report.get("findings") or []) + \
        (report.get("disputed_findings") or [])
    marks = [f.get("cross_family") for f in standing]
    lines += ["",
              "(b) run_review, blocking finding raised by an",
              "    unknown-family seat, second seat also unknown:",
              f"    standing findings' cross_family marks: {marks}",
              f"    gate = {report['gate']}"]
    assert marks and all(m == "unknown_family" for m in marks)
    lines.append("    ASSERTION HELD: marked 'unknown_family' —"
                 " never multi-family, never confirmed away.")

    # (c) record-verify two_families
    record = {
        "mode": "review", "gate": "pass", "degraded": False,
        "test_results": [{"command": "true", "ok": True}],
        "reviewer_reports": [
            {"provider": "vendor-a", "lens": "correctness",
             "status": "ok", "family": "unknown"},
            {"provider": "vendor-b", "lens": "operations",
             "status": "ok", "family": "unknown"}],
        "coverage": {"complete": True, "files": {}},
        "findings": [],
    }
    checks = core.verify_record(record)
    tf = [c for c in checks["checks"] if c["name"] == "two_families"]
    lines += ["",
              "(c) verify_record on an all-unknown record:",
              f"    two_families ok = {tf[0]['ok']} "
              f"({tf[0]['detail']})"]
    assert tf and tf[0]["ok"] is False
    lines.append("    ASSERTION HELD: two unknown seats cannot"
                 " satisfy the two-family independence check.")
    lines += ["",
              "PROBE OUTCOME: fail-closed on construction, Tech",
              "Lead selection, cross-family treatment, and",
              "record verification. Supports the pre-filled",
              "recommendation: sustain refutation (probe-backed)."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "unknown-family-3d9645200bc5.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
