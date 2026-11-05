#!/usr/bin/env python3
"""Score a Baseline v2 confirmation attempt (registration §1.4).

Reads bench/confirmation-v2/attempt-<n>.jsonl and prints a JSON
scoring document. Metrics use the §2.2 names and the
registration's definitions — no others:

  * Merged blocking precision (A5 holdout): over merged
    gate-level findings of blocking tier (blocker + major, as
    recorded AFTER the balanced profile applied), the fraction
    matching a labelled defect, where all findings matching one
    defect count once for that defect. A finding matches a
    defect via bench._finding_matches (the v1 predicate);
    duplicates removed are reported with the figure.
  * Recall (A5): labelled defects found / labelled defects,
    bench.score_case semantics (a defect is found when any
    finding matches it, whatever severity survived). Blocking
    recall (the matched finding itself blocking-tier) is
    reported alongside.
  * Clean-case BLOCKED rate (expanded clean, n=35): fraction of
    cases whose recorded gate is BLOCKED, with the Wilson 95%
    upper bound the registration's closure test uses. The
    any-finding rate and blocking-finding count per case ride
    alongside as noise measures.

Intervals: case-level bootstrap (20,000 resamples, seed
20261104 — the step-1/step-4 house method) for precision and
recall; Wilson 95% for the clean BLOCKED rate (and as
cross-check elsewhere).
"""

import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WORKTREE, "src"))

from codereview import bench as bench_mod  # noqa: E402

SEED = 20261104
RESAMPLES = 20000


def wilson(k, n, z=1.959964):
    if n == 0:
        return [None, None]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
            / denom)
    return [round(max(0.0, centre - half), 3),
            round(min(1.0, centre + half), 3)]


def bootstrap(values_fn, items, seed=SEED, resamples=RESAMPLES):
    """Percentile interval of values_fn over case-level resamples."""
    rng = random.Random(seed)
    n = len(items)
    points = []
    for _ in range(resamples):
        sample = [items[rng.randrange(n)] for _ in range(n)]
        v = values_fn(sample)
        if v is not None:
            points.append(v)
    if not points:
        return [None, None]
    points.sort()
    lo = points[int(0.025 * (len(points) - 1))]
    hi = points[int(0.975 * (len(points) - 1))]
    return [round(lo, 3), round(hi, 3)]


def merged_blocking_precision(case_rows):
    """case_rows: [{expected: [...], findings: [...]}] ->
    (precision, D, U, duplicates_removed). D = distinct defects
    matched by >=1 blocking finding; U = blocking findings
    matching no defect; duplicates removed = blocking findings
    matching some defect, minus D."""
    D = 0
    U = 0
    matching = 0
    for row in case_rows:
        blocking = [f for f in row["findings"]
                    if (f.get("severity") or "").lower()
                    in bench_mod.BLOCKING_SEVERITIES]
        matched_defects = set()
        for f in blocking:
            hit = None
            for i, exp in enumerate(row["expected"]):
                ok, _ = bench_mod._finding_matches(exp, f)
                if ok:
                    hit = i
                    break
            if hit is None:
                U += 1
            else:
                matching += 1
                matched_defects.add(hit)
        D += len(matched_defects)
    denom = D + U
    precision = (D / denom) if denom else None
    return precision, D, U, matching - D


def score_attempt(path):
    records = [json.loads(line) for line in open(path, encoding="utf-8")
               if line.strip()]
    corpus = {c["id"]: c
              for c in bench_mod.load_corpus(
                  os.path.join(WORKTREE, "bench", "corpus"))}
    sys.path.insert(0, HERE)
    import run_confirmation_v2 as drv
    expanded = {c["id"]: c for c in drv.load_expanded_clean()}

    holdout_recs = [r for r in records if r["split"] == "holdout"]
    clean_recs = [r for r in records
                  if r["split"] == "expanded-clean"]

    # ---- A5 holdout: recall + merged blocking precision
    case_rows = []
    per_case = []
    defects_found = 0
    defects_blocking_found = 0
    defects_total = 0
    for rec in holdout_recs:
        case = corpus[rec["case_id"]]
        scored = bench_mod.score_case(case, rec["findings"])
        defects_total += scored["expected_total"]
        defects_found += scored["matched"]
        defects_blocking_found += sum(
            1 for d in scored["defects"]
            if d["matched"] and not d["escaped"])
        case_rows.append({"case_id": rec["case_id"],
                          "expected": case["expected"],
                          "findings": rec["findings"]})
        per_case.append({
            "case_id": rec["case_id"], "gate": rec["gate"],
            "degraded": rec["degraded"],
            "expected": scored["expected_total"],
            "matched": scored["matched"],
            "escaped": scored["escaped"],
            "findings": scored["findings_total"],
            "false_positives_naive": scored["false_positives"],
        })
    precision, D, U, dupes = merged_blocking_precision(case_rows)

    def precision_of(rows):
        p, _, _, _ = merged_blocking_precision(rows)
        return p

    def recall_of(rows):
        num = den = 0
        for row in rows:
            case = corpus[row["case_id"]]
            s = bench_mod.score_case(case, row["findings"])
            num += s["matched"]
            den += s["expected_total"]
        return (num / den) if den else None

    prec_boot = bootstrap(precision_of, case_rows)
    rec_boot = bootstrap(recall_of, case_rows)
    recall = (defects_found / defects_total) if defects_total else None

    # ---- expanded clean stratum
    n_clean = len(clean_recs)
    blocked_clean = sum(1 for r in clean_recs
                         if (r["gate"] or "").lower() == "blocked")
    any_finding = sum(1 for r in clean_recs if r["findings"])
    blocking_per_case = [
        sum(1 for f in r["findings"]
            if (f.get("severity") or "").lower()
            in bench_mod.BLOCKING_SEVERITIES)
        for r in clean_recs]
    clean_rate = (blocked_clean / n_clean) if n_clean else None
    clean_wilson = wilson(blocked_clean, n_clean)
    clean_boot = bootstrap(
        lambda rows: (sum(1 for r in rows
                          if (r["gate"] or "").lower() == "blocked")
                      / len(rows)) if rows else None,
        clean_recs)

    # ---- run-level facts
    degraded = [r["case_id"] for r in records if r["degraded"]]
    seat_jobs = sum(len(r["reviewer_reports"]) for r in records)
    seat_ok = sum(1 for r in records for rep in r["reviewer_reports"]
                  if rep.get("status") == "ok")
    durations = sorted(r["duration_ms"] for r in records)

    def pct(p):
        if not durations:
            return None
        return round(durations[min(len(durations) - 1,
                                   int(p * len(durations)))] / 1000, 1)

    demotions = sum(len((r.get("gate_profile") or {}).get("demotions")
                        or []) for r in records)
    return {
        "records": len(records),
        "degraded_cases": degraded,
        "seat_jobs": seat_jobs, "seat_jobs_ok": seat_ok,
        "latency_s": {"p50": pct(0.5), "p95": pct(0.95)},
        "profile_demotions_total": demotions,
        "holdout": {
            "cases": len(holdout_recs),
            "defects_total": defects_total,
            "defects_found": defects_found,
            "recall": recall,
            "recall_bootstrap95": rec_boot,
            "recall_wilson95": wilson(defects_found, defects_total),
            "defects_found_at_blocking": defects_blocking_found,
            "blocking_recall": (defects_blocking_found / defects_total)
            if defects_total else None,
            "merged_blocking_precision": precision,
            "precision_D": D, "precision_U": U,
            "precision_duplicates_removed": dupes,
            "precision_bootstrap95": prec_boot,
            "precision_wilson95": wilson(D, D + U),
            "per_case": per_case,
        },
        "expanded_clean": {
            "cases": n_clean,
            "blocked": blocked_clean,
            "blocked_rate": clean_rate,
            "blocked_wilson95": clean_wilson,
            "blocked_bootstrap95": clean_boot,
            "any_finding_cases": any_finding,
            "any_finding_rate": (any_finding / n_clean)
            if n_clean else None,
            "blocking_findings_total": sum(blocking_per_case),
            "blocking_findings_per_case": (
                round(sum(blocking_per_case) / n_clean, 2)
                if n_clean else None),
            "per_case": [{
                "case_id": r["case_id"], "gate": r["gate"],
                "degraded": r["degraded"],
                "findings": len(r["findings"]),
                "blocking_findings": b,
                "demotions": len((r.get("gate_profile") or {})
                                 .get("demotions") or []),
            } for r, b in zip(clean_recs, blocking_per_case)],
        },
    }


if __name__ == "__main__":
    path = sys.argv[1]
    print(json.dumps(score_attempt(path), indent=1))
