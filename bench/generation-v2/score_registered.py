#!/usr/bin/env python3
"""Scoring + secondary analyses for the registered Baseline v2
confirmation attempt (pre-registration 2026-11-05 §1, Addendum A
items 6-7). The registered metrics come from the FROZEN scorer
(bench/scripts/score_confirmation_v2.py), used unchanged; this
script adds only what the addendum requires around it:

  * the item-6 PESSIMISTIC view: the scorer scores the records
    present (the scored-only view); cases that ended unscored
    are absent from the attempt file, so the pessimistic view
    re-denominates over the full registered universe (44 cases):
    an unscored defect case's labelled defects count as misses
    (recall), an unscored clean case counts as BLOCKED (clean
    rate), and an unscored case's blocking findings would count
    as false positives (precision) — in this machinery an
    unscored case has no attempt record and therefore no
    findings, so the precision numerator/denominator are
    unchanged (stated, not assumed silently);
  * item 7.1 paired strict-vs-balanced on the identical frozen
    records: a case's strict findings are its recorded findings
    with every B1 demotion reversed (severity restored from
    profile_demotion.from; B1 never deletes a finding, so
    any-severity recall is identical by construction — verified
    on the records, not just asserted). The strict GATE is
    reconstructed descriptively: blocked iff any strict
    blocking-tier finding exists, else the recorded gate
    (demotion reversal can only add blocking findings);
  * item 7.2 per-stratum fallback counts from the generation
    records (latest record per case x seat x lens);
  * threshold verdicts under BOTH views (registration §1.5).

Usage: score_registered.py [attempt-jsonl] [generation-jsonl]
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(WORKTREE, "bench", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(WORKTREE, "src"))

import score_confirmation_v2 as scorer  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402

ATTEMPT = os.path.join(HERE, "attempt-1.jsonl")
GENERATION = os.path.join(HERE, "generation-attempt-1.jsonl")


def strict_findings(rec):
    out = []
    for f in rec["findings"]:
        f = dict(f)
        dem = f.get("profile_demotion")
        if dem and dem.get("from"):
            f["severity"] = dem["from"]
        out.append(f)
    return out


def paired(records, corpus, expanded):
    a5 = [r for r in records if r["split"] == "holdout"]
    clean = [r for r in records if r["split"] == "expanded-clean"]
    rows = {"a5": [], "clean_blocked_balanced": [],
            "clean_blocked_strict": []}
    for rec in a5:
        case = corpus[rec["case_id"]]
        bal = bench_mod.score_case(case, rec["findings"])
        st = bench_mod.score_case(case, strict_findings(rec))
        rows["a5"].append({
            "case_id": rec["case_id"],
            "expected": bal["expected_total"],
            "found_balanced": bal["matched"],
            "found_strict": st["matched"],
            "blocking_balanced": sum(
                1 for d in bal["defects"]
                if d["matched"] and not d["escaped"]),
            "blocking_strict": sum(
                1 for d in st["defects"]
                if d["matched"] and not d["escaped"]),
        })
    for rec in clean:
        if (rec["gate"] or "").lower() == "blocked":
            rows["clean_blocked_balanced"].append(rec["case_id"])
        strict_blocked = any(
            (f.get("severity") or "").lower()
            in bench_mod.BLOCKING_SEVERITIES
            for f in strict_findings(rec))
        if strict_blocked:
            rows["clean_blocked_strict"].append(rec["case_id"])
    return rows


def main(argv):
    attempt_path = argv[1] if len(argv) > 1 else ATTEMPT
    gen_path = argv[2] if len(argv) > 2 else GENERATION
    records = [json.loads(l) for l in open(attempt_path,
                                           encoding="utf-8")
               if l.strip()]
    scored = scorer.score_attempt(attempt_path)

    corpus = {c["id"]: c for c in bench_mod.load_corpus(
        os.path.join(WORKTREE, "bench", "corpus"))}
    sys.path.insert(0, SCRIPTS)
    import run_confirmation_v2 as conf
    expanded = {c["id"]: c for c in conf.load_expanded_clean()}
    holdout_ids = sorted(c for c in corpus
                         if corpus[c]["split"] == "holdout")
    clean_ids = sorted(expanded)
    present = {r["case_id"] for r in records}
    unscored_holdout = [c for c in holdout_ids if c not in present]
    unscored_clean = [c for c in clean_ids if c not in present]
    unscored = unscored_holdout + unscored_clean

    # --- pessimistic view (item 6)
    defects_total_all = sum(len(corpus[c]["expected"])
                            for c in holdout_ids)
    found = scored["holdout"]["defects_found"]
    pess_recall = (found / defects_total_all
                   if defects_total_all else None)
    blocked_present = scored["expanded_clean"]["blocked"]
    pess_blocked = blocked_present + len(unscored_clean)
    pess_clean_rate = pess_blocked / len(clean_ids)
    pess_clean_wilson = scorer.wilson(pess_blocked, len(clean_ids))
    pess_precision = scored["holdout"]["merged_blocking_precision"]

    def verdicts(view):
        prec = (scored["holdout"]["merged_blocking_precision"]
                if view == "scored" else pess_precision)
        rec = (scored["holdout"]["recall"] if view == "scored"
               else pess_recall)
        if view == "scored":
            rate = scored["expanded_clean"]["blocked_rate"]
            wup = scored["expanded_clean"]["blocked_wilson95"][1]
        else:
            rate, wup = pess_clean_rate, pess_clean_wilson[1]
        return {
            "precision_ge_0.50": (prec is not None
                                  and prec >= 0.50),
            "recall_ge_0.95": (rec is not None and rec >= 0.95),
            "clean_point_le_0.20": (rate is not None
                                    and rate <= 0.20),
            "clean_wilson_upper_le_0.30": (wup is not None
                                           and wup <= 0.30),
        }

    # --- item 7.2 fallback counts (latest generation records)
    latest = {}
    if os.path.isfile(gen_path):
        for line in open(gen_path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                latest[(r["case_id"], r["seat"], r["lens"])] = r
    fb_rows = [r for r in latest.values()
               if r.get("fallback_for") and r["status"] == "valid"]
    fb_by = {}
    for r in fb_rows:
        key = (r["split"], r["served_by"])
        fb_by[key] = fb_by.get(key, 0) + 1

    out = {
        "records_scored": len(records),
        "unscored_cases": unscored,
        "unscored_count": len(unscored),
        "unscored_within_cap_2": len(unscored) <= 2,
        "degraded_scored_cases": scored["degraded_cases"],
        "scored_only_view": scored,
        "pessimistic_view": {
            "recall": pess_recall,
            "recall_defects_total": defects_total_all,
            "merged_blocking_precision": pess_precision,
            "clean_blocked": pess_blocked,
            "clean_cases_total": len(clean_ids),
            "clean_blocked_rate": pess_clean_rate,
            "clean_wilson95": pess_clean_wilson,
        },
        "threshold_verdicts": {
            "scored_only": verdicts("scored"),
            "pessimistic": verdicts("pessimistic"),
        },
        "paired_strict_balanced": paired(records, corpus, expanded),
        "fallback_served_records": {
            "total": len(fb_rows),
            "by_split_and_serving_seat": {
                f"{k[0]}|{k[1]}": v for k, v in sorted(fb_by.items())},
            "detail": [{"case_id": r["case_id"],
                        "split": r["split"],
                        "seat": r["seat"], "lens": r["lens"],
                        "served_by": r["served_by"],
                        "fallback_for": r["fallback_for"]}
                       for r in sorted(
                           fb_rows,
                           key=lambda r: (r["split"], r["case_id"]))],
        },
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
