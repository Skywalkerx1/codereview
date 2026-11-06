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


# ==================================================================
# B2 confirmation scoring (pre-registration-b2-2026-11-05 §4/§5/
# §7/§8). The generation-v3 extension of the one scoring lineage:
# the metric primitives above (merged_blocking_precision, wilson,
# bootstrap, bench.score_case) are reused unchanged; what is new
# is the strata/view/threshold assembly the B2 registration
# registers. Scored-only and pessimistic views are both computed
# and both gated (§5); paired baselines re-evaluate the SAME
# stored responses through core.evaluate_gate_policy (§6.1 of
# the solution), exactly as the dev pilot's scorer did.

V3_PREDICTION = {
    "clean_blocked_point": 0.080,
    "clean_blocked_interval95": [0.022, 0.25],
    "recall_any_severity_point": 1.000,
    "recall_any_severity_interval95": [0.898, 1.0],
    "recall_blocking_tier_point": 0.706,
    "recall_blocking_tier_interval95": [0.538, 0.832],
    "merged_blocking_precision_point": 1.000,
}
V3_CAP = 4          # registration §5: unscored + corrob-unavail
V3_CLEAN_POINT_MAX = 0.20
V3_CLEAN_WILSON_MAX = 0.30
V3_RECALL_BLOCKING_MIN = 0.60
V3_RECALL_ANY_MIN = 0.95
V3_PRECISION_MIN = 0.50


def _v3_family_map():
    sys.path.insert(0, HERE)
    import run_panel_baseline as panel_driver
    cfg = bench_mod.load_config(panel_driver.CONFIG_SPEC)
    fam = {}
    for name, meta in (cfg["seat_meta"] or {}).items():
        fam[name] = (meta or {}).get("family") or "unknown"
    fam["deterministic"] = "deterministic"
    return fam


def _v3_base_findings(rec):
    """The record's findings with profile demotions restored —
    the pre-profile finding set the paired replays evaluate."""
    import copy
    out = []
    for f in rec["findings"]:
        g = copy.deepcopy(f)
        dem = g.get("profile_demotion")
        if dem:
            g["severity"] = dem.get("from") or g.get("severity")
        out.append(g)
    return out


def _v3_evaluate(rec, profile, family):
    from codereview import core as core_mod
    outcomes = {}
    for f in rec["findings"]:
        corr = f.get("corroboration") or {}
        if corr:
            outcomes[f.get("id")] = corr
    applied, _dem = core_mod.evaluate_gate_policy(
        _v3_base_findings(rec), profile,
        family_by_source=family, confirmation_outcomes=outcomes)
    return applied


def _v3_is_blocking(f):
    return (f.get("severity") or "").lower() \
        in bench_mod.BLOCKING_SEVERITIES


def _v3_defect_metrics(rows):
    """rows: [{case_id, expected, findings}] -> recall (both
    definitions), merged blocking precision, intervals."""
    found_any = found_blk = total = 0
    for r in rows:
        sc = bench_mod.score_case(
            {"id": r["case_id"], "expected": r["expected"]},
            r["findings"])
        found_any += sc["matched"]
        found_blk += sum(1 for d in sc["defects"]
                         if d["matched"] and not d["escaped"])
        total += len(r["expected"])
    prec, d, u, dup = merged_blocking_precision(rows)

    def precision_of(sample):
        p, _, _, _ = merged_blocking_precision(sample)
        return p

    def recall_any_of(sample):
        num = den = 0
        for r in sample:
            s = bench_mod.score_case(
                {"id": r["case_id"], "expected": r["expected"]},
                r["findings"])
            num += s["matched"]
            den += len(r["expected"])
        return (num / den) if den else None

    def recall_blk_of(sample):
        num = den = 0
        for r in sample:
            s = bench_mod.score_case(
                {"id": r["case_id"], "expected": r["expected"]},
                r["findings"])
            num += sum(1 for dd in s["defects"]
                       if dd["matched"] and not dd["escaped"])
            den += len(r["expected"])
        return (num / den) if den else None

    return {
        "defects": total,
        "found_any_severity": found_any,
        "recall_any_severity": (found_any / total) if total
                               else None,
        "recall_any_bootstrap95": bootstrap(recall_any_of, rows),
        "recall_any_wilson95": wilson(found_any, total),
        "found_blocking_tier": found_blk,
        "recall_blocking_tier": (found_blk / total) if total
                                else None,
        "recall_blocking_bootstrap95": bootstrap(recall_blk_of,
                                                 rows),
        "recall_blocking_wilson95": wilson(found_blk, total),
        "merged_blocking_precision": prec,
        "precision_D": d, "precision_U": u,
        "precision_duplicates_removed": dup,
        "precision_bootstrap95": bootstrap(precision_of, rows),
        "precision_wilson95": wilson(d, d + u),
    }


def _v3_clean_metrics(rows):
    """rows: [{case_id, blocked}] -> rate + intervals."""
    blocked = sum(1 for r in rows if r["blocked"])
    n = len(rows)
    return {
        "cases": n, "blocked": blocked,
        "rate": (blocked / n) if n else None,
        "wilson95": wilson(blocked, n),
        "bootstrap95": bootstrap(
            lambda sample: (sum(1 for r in sample if r["blocked"])
                            / len(sample)) if sample else None,
            rows),
    }


def _v3_view_metrics(clean_rows, defect_rows, all_rows):
    cm = _v3_clean_metrics(clean_rows)
    dm = _v3_defect_metrics(defect_rows)
    prec_all, ad, au, adup = merged_blocking_precision(all_rows)
    return {
        "clean": cm,
        "defects": dm,
        "precision_all_cases_descriptive": prec_all,
        "precision_all_cases_D": ad,
        "precision_all_cases_U": au,
        "J_any_severity": (
            dm["recall_any_severity"] - cm["rate"])
        if dm["recall_any_severity"] is not None
        and cm["rate"] is not None else None,
        "J_blocking_tier": (
            dm["recall_blocking_tier"] - cm["rate"])
        if dm["recall_blocking_tier"] is not None
        and cm["rate"] is not None else None,
    }


def _v3_thresholds(view):
    cm, dm = view["clean"], view["defects"]
    w = cm["wilson95"]
    return {
        "clean_blocked_point": (
            cm["rate"] is not None
            and cm["rate"] <= V3_CLEAN_POINT_MAX),
        "clean_blocked_wilson_upper": (
            w[1] is not None and w[1] <= V3_CLEAN_WILSON_MAX),
        "recall_blocking_tier_primary": (
            dm["recall_blocking_tier"] is not None
            and dm["recall_blocking_tier"]
            >= V3_RECALL_BLOCKING_MIN),
        "recall_any_severity_floor": (
            dm["recall_any_severity"] is not None
            and dm["recall_any_severity"] >= V3_RECALL_ANY_MIN),
        "merged_blocking_precision": (
            dm["merged_blocking_precision"] is not None
            and dm["merged_blocking_precision"]
            >= V3_PRECISION_MIN),
    }


def score_attempt_v3(records_path, gen3_dir=None,
                     generation_path=None):
    """Score a B2 confirmation attempt (registration §4–§8).

    records_path: the attempt records JSONL (complete cases
    only — generation writes no record for an incomplete case).
    gen3_dir: the sealed set directory the expected cases load
    from (default bench/generation-v3). generation_path: the
    per-case generation records JSONL, for the §7 secondary
    analyses (fallback counts, failure-vs-feature); optional.
    """
    if gen3_dir is None:
        gen3_dir = os.path.join(WORKTREE, "bench", "generation-v3")
    cases = {}
    for c in bench_mod.load_corpus(gen3_dir):
        with open(os.path.join(c["dir"], "case.json"),
                  encoding="utf-8") as fh:
            c = dict(c, stratum=json.load(fh).get("stratum"))
        cases[c["id"]] = c
    records = {}
    with open(records_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                records[r["case_id"]] = r
    unknown = [cid for cid in records if cid not in cases]
    if unknown:
        raise ValueError(
            f"records name cases outside the sealed set: "
            f"{unknown[:5]}")

    def is_clean(case):
        return not case["expected"]

    def corrob_unavail(rec):
        return any("corroboration unavailable" in str(cause)
                   for cause in rec.get("degraded_causes") or [])

    unscored = sorted(cid for cid in cases if cid not in records)
    corrob = sorted(cid for cid, r in records.items()
                    if corrob_unavail(r))
    cap_used = len(unscored) + len(corrob)
    void = cap_used > V3_CAP

    # ---- rows per view
    def defect_rows(view):
        rows = []
        for cid, case in cases.items():
            if is_clean(case):
                continue
            rec = records.get(cid)
            if rec is None:
                if view == "pessimistic":
                    rows.append({"case_id": cid,
                                 "expected": case["expected"],
                                 "findings": []})
                continue
            rows.append({"case_id": cid,
                         "expected": case["expected"],
                         "findings": rec["findings"]})
        return rows

    def clean_rows(view):
        rows = []
        for cid, case in cases.items():
            if not is_clean(case):
                continue
            rec = records.get(cid)
            if rec is None:
                if view == "pessimistic":
                    rows.append({"case_id": cid, "blocked": True})
                continue
            blocked = (rec.get("gate") or "").lower() == "blocked"
            if view == "pessimistic" and corrob_unavail(rec) \
                    and (rec.get("unverified_majors") or []):
                blocked = True
            rows.append({"case_id": cid, "blocked": blocked})
        return rows

    def all_rows(view):
        return defect_rows(view) + [
            {"case_id": cid,
             "expected": cases[cid]["expected"],
             "findings": records[cid]["findings"]}
            for cid in cases
            if is_clean(cases[cid]) and cid in records]

    views = {}
    for view in ("scored_only", "pessimistic"):
        views[view] = _v3_view_metrics(
            clean_rows(view), defect_rows(view), all_rows(view))
        views[view]["thresholds"] = _v3_thresholds(views[view])
        views[view]["thresholds_all"] = all(
            views[view]["thresholds"].values())

    # ---- strata detail (scored-only view definitions; counts
    # always over the full stratum with scored/unscored stated)
    strata = {}
    for stratum in ("clean-authored", "clean-realworld",
                    "defect-injected", "defect-realworld"):
        ids = [cid for cid, c in cases.items()
               if c["stratum"] == stratum]
        scored_ids = [cid for cid in ids if cid in records]
        entry = {"cases": len(ids), "scored": len(scored_ids),
                 "unscored": len(ids) - len(scored_ids)}
        if stratum.startswith("clean"):
            entry["clean_scored_only"] = _v3_clean_metrics([
                {"case_id": cid,
                 "blocked": (records[cid].get("gate") or "").lower()
                 == "blocked"} for cid in scored_ids])
        else:
            entry["defects_scored_only"] = _v3_defect_metrics([
                {"case_id": cid,
                 "expected": cases[cid]["expected"],
                 "findings": records[cid]["findings"]}
                for cid in scored_ids])
        strata[stratum] = entry

    # ---- paired baselines on the same responses (§8), scored
    # cases only; the live row is the scored-only view above.
    family = _v3_family_map()
    scored_clean = [cid for cid, c in cases.items()
                    if is_clean(c) and cid in records]
    scored_defect = [cid for cid, c in cases.items()
                     if not is_clean(c) and cid in records]

    def baseline_rows(findings_by_cid, blocked_by_cid):
        d_rows = [{"case_id": cid,
                   "expected": cases[cid]["expected"],
                   "findings": findings_by_cid[cid]}
                  for cid in scored_defect]
        c_rows = [{"case_id": cid, "blocked": blocked_by_cid[cid]}
                  for cid in scored_clean]
        dm = _v3_defect_metrics(d_rows)
        cm = _v3_clean_metrics(c_rows)
        return {
            "clean_blocked_rate": cm["rate"],
            "recall_any_severity": dm["recall_any_severity"],
            "recall_blocking_tier": dm["recall_blocking_tier"],
            "merged_blocking_precision":
                dm["merged_blocking_precision"],
            "J_any_severity": (
                dm["recall_any_severity"] - cm["rate"])
            if dm["recall_any_severity"] is not None
            and cm["rate"] is not None else None,
            "J_blocking_tier": (
                dm["recall_blocking_tier"] - cm["rate"])
            if dm["recall_blocking_tier"] is not None
            and cm["rate"] is not None else None,
        }

    def replay(profile):
        f_by, b_by = {}, {}
        for cid in scored_clean + scored_defect:
            applied = _v3_evaluate(records[cid], profile, family)
            f_by[cid] = applied
            b_by[cid] = any(_v3_is_blocking(f) for f in applied)
        return baseline_rows(f_by, b_by)

    det_f, det_b = {}, {}
    for cid in scored_clean + scored_defect:
        det = [f for f in _v3_base_findings(records[cid])
               if "deterministic" in (f.get("sources") or [])
               and _v3_is_blocking(f)]
        det_f[cid] = det
        det_b[cid] = bool(det)
    baselines = {
        "live_corroborated": baseline_rows(
            {cid: records[cid]["findings"]
             for cid in scored_clean + scored_defect},
            {cid: (records[cid].get("gate") or "").lower()
             == "blocked"
             for cid in scored_clean + scored_defect}),
        "strict_paired": replay("strict"),
        "corroborated_paired": replay("corroborated"),
        "deterministic_only": baseline_rows(det_f, det_b),
        "always_pass": {"clean_blocked_rate": 0.0,
                        "recall_any_severity": 0.0,
                        "recall_blocking_tier": 0.0,
                        "merged_blocking_precision": None,
                        "J_any_severity": 0.0,
                        "J_blocking_tier": 0.0},
        "always_block": {"clean_blocked_rate": 1.0,
                         "recall_any_severity": 1.0,
                         "recall_blocking_tier": 1.0,
                         "merged_blocking_precision": None,
                         "J_any_severity": 0.0,
                         "J_blocking_tier": 0.0},
    }
    agree = total = 0
    for cid in scored_clean + scored_defect:
        applied = _v3_evaluate(records[cid], "corroborated",
                               family)
        replay_blocked = any(_v3_is_blocking(f) for f in applied)
        live_blocked = any(_v3_is_blocking(f)
                           for f in records[cid]["findings"])
        total += 1
        agree += (replay_blocked == live_blocked)

    # ---- secondary analyses (§7, descriptive)
    ev_breakdown, corr_outcomes = {}, {}
    unverified_total = 0
    degraded_by_stratum, cause_tally = {}, {}
    for cid, rec in records.items():
        unverified_total += len(rec.get("unverified_majors")
                                or [])
        if rec.get("degraded"):
            degraded_by_stratum.setdefault(
                cases[cid]["stratum"], []).append(cid)
            for cause in rec.get("degraded_causes") or []:
                cause_tally[str(cause)] = \
                    cause_tally.get(str(cause), 0) + 1
        for f in rec["findings"]:
            if _v3_is_blocking(f):
                cls = f.get("evidence_class") or "unstamped"
                ev_breakdown[cls] = ev_breakdown.get(cls, 0) + 1
            corr = f.get("corroboration") or {}
            if corr:
                o = corr.get("outcome") or "?"
                corr_outcomes[o] = corr_outcomes.get(o, 0) + 1
    secondary = {
        "blocking_findings_by_evidence_class": ev_breakdown,
        "corroboration_outcomes": corr_outcomes,
        "unverified_majors_total": unverified_total,
        "degraded_by_stratum": degraded_by_stratum,
        "degraded_causes_tally": cause_tally,
        "paired_replay_agreement": {"cases": total,
                                    "agree": agree},
    }
    if generation_path:
        gen_recs = [json.loads(line) for line in
                    open(generation_path, encoding="utf-8")
                    if line.strip()]
        fb_by_stratum = {}
        fail_by_case = {}
        for g in gen_recs:
            cid = g["case_id"]
            if cid not in cases:
                continue
            if g.get("fallback_for"):
                st = cases[cid]["stratum"]
                fb_by_stratum[st] = fb_by_stratum.get(st, 0) + 1
            agg = fail_by_case.setdefault(
                cid, {"failures": 0, "retries": 0})
            agg["failures"] += g.get("failure_count") or 0
            agg["retries"] += g.get("retries") or 0
        xs, ys = [], []
        for cid, agg in fail_by_case.items():
            xs.append(len(cases[cid]["diff"]))
            ys.append(agg["failures"])
        pearson = None
        if len(xs) > 2:
            mx = sum(xs) / len(xs)
            my = sum(ys) / len(ys)
            num = sum((x - mx) * (y - my)
                      for x, y in zip(xs, ys))
            den = (sum((x - mx) ** 2 for x in xs)
                   * sum((y - my) ** 2 for y in ys)) ** 0.5
            pearson = round(num / den, 3) if den else None
        fail_strata = {}
        for cid, agg in fail_by_case.items():
            st = cases[cid]["stratum"]
            a = fail_strata.setdefault(
                st, {"cases": 0, "failures": 0, "retries": 0})
            a["cases"] += 1
            a["failures"] += agg["failures"]
            a["retries"] += agg["retries"]
        secondary["fallback_records_by_stratum"] = fb_by_stratum
        secondary["failure_vs_features"] = {
            "pearson_failures_vs_diff_chars": pearson,
            "by_stratum": fail_strata,
            "note": "descriptive only (§7 item 3): if failures "
                    "correlate with case features the reported "
                    "bounds are widened and the correlation "
                    "stated — no such widening is applied "
                    "mechanically here; the correlation is "
                    "reported for the results document.",
        }

    passed = (not void) and all(
        v["thresholds_all"] for v in views.values())
    return {
        "run": "b2-confirmation",
        "records": len(records),
        "expected_cases": len(cases),
        "unscored_cases": unscored,
        "corroboration_unavailable_cases": corrob,
        "cap_used": cap_used, "cap": V3_CAP, "void": void,
        "views": views,
        "strata": strata,
        "baselines": baselines,
        "secondary": secondary,
        "prediction_registered": V3_PREDICTION,
        "verdict": "VOID" if void else (
            "PASS" if passed else "FAIL"),
    }


if __name__ == "__main__":
    _args = sys.argv[1:]
    if "--v3" in _args:
        _args.remove("--v3")

        def _opt(name):
            if name in _args:
                i = _args.index(name)
                val = _args[i + 1]
                del _args[i:i + 2]
                return val
            return None

        _gen = _opt("--generation")
        _gen3 = _opt("--gen3")
        print(json.dumps(
            score_attempt_v3(_args[0], gen3_dir=_gen3,
                             generation_path=_gen), indent=1))
    else:
        print(json.dumps(score_attempt(_args[0]), indent=1))
