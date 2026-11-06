#!/usr/bin/env python3
"""Score the B2 dev pilot (expert solution §6.2/§6.3).

Reads pilot-records.jsonl (ONE live `corroborated` run per case)
and produces pilot-results.json + PILOT.md in the standard
benchmark shape:

  * live corroborated: gates as recorded by the full pipeline.
  * paired profiles on the SAME responses: base findings
    (profile demotions restored) re-evaluated through the ONE
    entry point, core.evaluate_gate_policy (§6.1) — strict,
    balanced, and corroborated with the live run's own
    confirmation outcomes supplied (the replay must reproduce
    the live profile-stage decisions; agreement is reported).
  * trivial baselines: always-pass, always-block,
    deterministic-only.
  * label-adjusted clean view: expanded-clean cases carrying a
    dated 2026-11-05 A1 amendment (real defects found in
    "clean" code) are excluded from the adjusted clean stratum.
  * the §6.3 numeric prediction for the future registered
    confirmation, derived from the pilot numbers below.

Definitions match the Step-1 sweep exactly (bench matching,
score_case recall, score_confirmation_v2 merged precision,
Wilson 95%).
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WORKTREE, "bench", "scripts"))
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, HERE)

import run_panel_baseline as panel_driver  # noqa: E402
import score_confirmation_v2 as sc2  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core as core_mod  # noqa: E402
from run_pilot import load_expanded  # noqa: E402

BLOCKING = ("blocker", "major")
FAMILY = {}
_cfg = bench_mod.load_config(panel_driver.CONFIG_SPEC)
for _name, _meta in (_cfg["seat_meta"] or {}).items():
    FAMILY[_name] = (_meta or {}).get("family") or "unknown"
FAMILY["deterministic"] = "deterministic"


def base_findings(rec):
    out = []
    for f in rec["findings"]:
        g = copy.deepcopy(f)
        dem = g.get("profile_demotion")
        if dem:
            g["severity"] = dem.get("from") or g.get("severity")
        out.append(g)
    return out


def is_blocking(sev):
    return sev in BLOCKING


def defect_metrics(rows):
    """rows: [{expected, findings}] -> recall (any sev),
    recall (blocking tier), merged blocking precision."""
    found_any = found_blk = total = 0
    for r in rows:
        sc = bench_mod.score_case(
            {"id": r["case_id"], "expected": r["expected"]},
            r["findings"])
        found_any += sc["matched"]
        found_blk += sum(1 for d in sc["defects"]
                         if d["matched"] and not d["escaped"])
        total += len(r["expected"])
    prec, d, u, dup = sc2.merged_blocking_precision(rows)
    return {
        "defects": total,
        "recall_any_severity": (found_any / total) if total
                               else None,
        "recall_blocking_tier": (found_blk / total) if total
                                else None,
        "merged_blocking_precision": prec,
        "precision_D": d, "precision_U": u,
        "precision_duplicates_removed": dup,
        "wilson_recall_any": sc2.wilson(found_any, total),
        "wilson_recall_blocking": sc2.wilson(found_blk, total),
    }


def clean_metrics(rows):
    blocked = sum(1 for r in rows if r["blocked"])
    n = len(rows)
    return {"cases": n, "blocked": blocked,
            "rate": (blocked / n) if n else None,
            "wilson95": sc2.wilson(blocked, n)}


def evaluate(rec, profile):
    outcomes = {}
    for f in rec["findings"]:
        corr = f.get("corroboration") or {}
        if corr:
            outcomes[f.get("id")] = corr
    applied, _dem = core_mod.evaluate_gate_policy(
        base_findings(rec), profile, family_by_source=FAMILY,
        confirmation_outcomes=outcomes)
    return applied


def main():
    recs = {}
    with open(os.path.join(HERE, "pilot-records.jsonl"),
              encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                recs[r["case_id"]] = r
    corpus = bench_mod.load_corpus(
        os.path.join(WORKTREE, "bench", "corpus"))
    cases = {}
    for c in corpus:
        if c["split"] != "public":
            continue
        c = dict(c)
        # Public ground truth = ORIGINAL labels only (the
        # Step-1 sweep's rule): entries carrying an
        # "adjudication_added" marker are excluded.
        c["expected"] = [e for e in c["expected"]
                         if "adjudication_added" not in e]
        cases[c["id"]] = c
    for c in load_expanded():
        cases[c["id"]] = c
    missing = [cid for cid in cases if cid not in recs]
    if missing:
        print(f"ABORT: {len(missing)} cases without records: "
              f"{missing[:5]}", file=sys.stderr)
        return 2

    amended = set()
    exp_dir = os.path.join(WORKTREE, "bench", "expanded-clean")
    for cid in os.listdir(exp_dir):
        cj = os.path.join(exp_dir, cid, "case.json")
        if os.path.exists(cj):
            with open(cj, encoding="utf-8") as fh:
                if json.load(fh).get("label_amendments"):
                    amended.add(cid)

    def rows_for(profile, case_ids):
        out = []
        for cid in case_ids:
            rec = recs[cid]
            if profile == "live":
                findings = rec["findings"]
                blocked = rec["gate"] == "blocked"
            else:
                findings = evaluate(rec, profile)
                blocked = any(is_blocking(f.get("severity"))
                              for f in findings)
            out.append({"case_id": cid,
                        "expected": cases[cid]["expected"],
                        "findings": findings, "blocked": blocked})
        return out

    public_ids = [c for c in cases
                  if cases[c]["split"] == "public"]
    exp_ids = [c for c in cases
               if str(cases[c]["split"]).startswith("expanded")]
    clean = lambda ids: [c for c in ids
                         if not cases[c]["expected"]]
    defect = lambda ids: [c for c in ids if cases[c]["expected"]]
    bundles = {
        "public": (defect(public_ids), clean(public_ids)),
        "expanded": (defect(exp_ids), clean(exp_ids)),
        "combined": (defect(public_ids + exp_ids),
                     clean(public_ids + exp_ids)),
    }
    adj_clean_ids = [c for c in bundles["combined"][1]
                     if c not in amended]

    profiles = {}
    for profile in ("live", "strict", "balanced", "corroborated"):
        entry = {"bundles": {}}
        for bname, (d_ids, c_ids) in bundles.items():
            d_rows = rows_for(profile, d_ids)
            c_rows = rows_for(profile, c_ids)
            dm = defect_metrics(d_rows)
            cm = clean_metrics(c_rows)
            entry["bundles"][bname] = {
                "defects": dm, "clean": cm,
                "J": (dm["recall_any_severity"] - cm["rate"])
                     if dm["recall_any_severity"] is not None
                     and cm["rate"] is not None else None}
        profiles[profile] = entry

    # paired-replay agreement with the live profile stage
    agree = total = 0
    for cid, rec in recs.items():
        replay = evaluate(rec, "corroborated")
        replay_blocked = any(is_blocking(f.get("severity"))
                             for f in replay)
        live_blocked = any(
            is_blocking(f.get("severity"))
            for f in rec["findings"])
        total += 1
        agree += (replay_blocked == live_blocked)
    agreement = {"cases": total, "agree": agree}

    # trivial baselines (combined bundle, base findings)
    base_rows = {}
    for cid in bundles["combined"][0] + bundles["combined"][1]:
        base_rows[cid] = base_findings(recs[cid])
    det_rows_d, det_rows_c = [], []
    for cid in bundles["combined"][0]:
        det = [f for f in base_rows[cid]
               if "deterministic" in (f.get("sources") or [])
               and is_blocking(f.get("severity"))]
        det_rows_d.append({"case_id": cid,
                           "expected": cases[cid]["expected"],
                           "findings": det,
                           "blocked": bool(det)})
    for cid in bundles["combined"][1]:
        det = [f for f in base_rows[cid]
               if "deterministic" in (f.get("sources") or [])
               and is_blocking(f.get("severity"))]
        det_rows_c.append({"case_id": cid,
                           "expected": cases[cid]["expected"],
                           "findings": det, "blocked": bool(det)})
    baselines = {
        "always_pass": {"clean_rate": 0.0, "recall_any": 0.0,
                        "J": 0.0},
        "always_block": {"clean_rate": 1.0, "recall_any": 1.0,
                         "J": 0.0},
        "deterministic_only": {
            "clean": clean_metrics(det_rows_c),
            "defects": defect_metrics(det_rows_d)},
    }
    dm_det = baselines["deterministic_only"]["defects"]
    cm_det = baselines["deterministic_only"]["clean"]
    baselines["deterministic_only"]["J"] = (
        dm_det["recall_any_severity"] - cm_det["rate"])

    # live-run extras
    live = profiles["live"]["bundles"]["combined"]
    ev_breakdown = {}
    corr_outcomes = {}
    unverified_total = 0
    degraded_cases = []
    for cid, rec in recs.items():
        if rec["degraded"]:
            degraded_cases.append(cid)
        unverified_total += len(rec.get("unverified_majors")
                                or [])
        for f in rec["findings"]:
            if is_blocking(f.get("severity")):
                cls = f.get("evidence_class") or "unstamped"
                ev_breakdown[cls] = ev_breakdown.get(cls, 0) + 1
            corr = f.get("corroboration") or {}
            if corr:
                o = corr.get("outcome") or "?"
                corr_outcomes[o] = corr_outcomes.get(o, 0) + 1
    cause_tally = {}
    for cid in degraded_cases:
        for cause in recs[cid].get("degraded_causes") or []:
            cause_tally[cause] = cause_tally.get(cause, 0) + 1
    live_extras = {
        "degraded_cases": degraded_cases,
        "degraded_causes_tally": cause_tally,
        "unverified_majors_total": unverified_total,
        "blocking_findings_by_evidence_class": ev_breakdown,
        "corroboration_outcomes": corr_outcomes,
    }

    # label-adjusted clean view (live corroborated)
    adj_rows = rows_for("live", adj_clean_ids)
    adjusted_clean = clean_metrics(adj_rows)
    as_labelled_clean = live["clean"]

    # §6.3 prediction for the future registered confirmation,
    # derived from the pilot: fresh sets are correctly labelled
    # by construction, so the label-ADJUSTED clean rate is the
    # honest point estimate; intervals are the pilot Wilson 95%
    # on the adjusted counts. Recall/precision points are the
    # combined-bundle live figures with their Wilson intervals.
    dm = live["defects"]
    prediction = {
        "basis": "live corroborated pilot, combined dev "
                 "bundles; clean point from the label-adjusted "
                 "stratum (amended cases excluded)",
        "clean_BLOCKED_point": adjusted_clean["rate"],
        "clean_BLOCKED_interval95": adjusted_clean["wilson95"],
        "clean_BLOCKED_as_labelled_point": as_labelled_clean[
            "rate"],
        "recall_any_severity_point":
            dm["recall_any_severity"],
        "recall_any_severity_interval95":
            dm["wilson_recall_any"],
        "recall_blocking_tier_point":
            dm["recall_blocking_tier"],
        "recall_blocking_tier_interval95":
            dm["wilson_recall_blocking"],
        "merged_blocking_precision_point":
            dm["merged_blocking_precision"],
        "note": "Fresh-set sampling error on >=60 clean cases "
                "will be narrower than the pilot interval; the "
                "registered prediction is this point + interval "
                "as written, per solution \u00a76.3.",
    }

    results = {
        "run": "b2-dev-pilot",
        "profiles": profiles,
        "paired_replay_agreement": agreement,
        "baselines": baselines,
        "live_extras": live_extras,
        "amended_cases_excluded_from_adjusted_clean":
            sorted(amended),
        "adjusted_clean_live": adjusted_clean,
        "prediction": prediction,
    }
    with open(os.path.join(HERE, "pilot-results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, sort_keys=True)

    def pct(x):
        return "—" if x is None else f"{x:.3f}"

    lines = [
        "# Policy B2 dev pilot — results (2026-11-05)",
        "",
        "Live product pipeline, gate profile `corroborated`, "
        "v1 panel [openai, nvidia, deepseek], dev data only "
        "(public split + expanded stratum, labels as amended "
        "2026-11-05). Paired rows are the SAME responses "
        "re-evaluated offline through core.evaluate_gate_policy "
        "(§6.1); the live row is the full pipeline outcome.",
        "",
        "Provenance: 62 cases, one live run each. The main "
        "run's final record (xc-tz-aware-scheduling) flushed "
        "late and one case (xc-token-bucket-limiter) was "
        "completed by a same-day top-up run under the identical "
        "configuration; the duplicate tz-aware record was "
        "deduplicated keeping the main run's. The paired "
        "`strict`/`balanced` rows evaluate the B2-prompt "
        "responses under those policies — they are paired "
        "policy comparisons, not the v1 baseline numbers. "
        "14 of 62 runs are marked degraded, every one with "
        "'reviewer failure' among its causes (a seat failed "
        "and a fallback or partial panel served); gates were "
        "still decided on all 62. Under a registered run those "
        "degraded cases would matter — seat reliability is the "
        "pilot's main operational warning for Step 6.",
        "",
        "| profile | clean-BLOCKED (combined) | recall "
        "any-sev | recall blocking-tier | merged precision "
        "| J |",
        "|---|---|---|---|---|---|",
    ]
    for name in ("live", "strict", "balanced", "corroborated"):
        b = profiles[name]["bundles"]["combined"]
        lines.append(
            f"| {name} | {pct(b['clean']['rate'])} "
            f"({b['clean']['blocked']}/{b['clean']['cases']}) "
            f"| {pct(b['defects']['recall_any_severity'])} "
            f"| {pct(b['defects']['recall_blocking_tier'])} "
            f"| {pct(b['defects']['merged_blocking_precision'])} "
            f"| {pct(b['J'])} |")
    lines += [
        "",
        f"Trivial baselines (combined): always-pass "
        f"clean-BLOCKED 0.000 / recall 0.000 / J 0.000; "
        f"always-block 1.000 / 1.000 / J 0.000; "
        f"deterministic-only clean-BLOCKED "
        f"{pct(cm_det['rate'])}, recall "
        f"{pct(dm_det['recall_any_severity'])}, J "
        f"{pct(baselines['deterministic_only']['J'])}.",
        "",
        f"Live extras: degraded cases "
        f"{len(degraded_cases)} (causes: "
        f"{live_extras['degraded_causes_tally']}); "
        f"unverified majors "
        f"{unverified_total}; blocking findings by evidence "
        f"class {ev_breakdown}; corroboration outcomes "
        f"{corr_outcomes}; paired-replay agreement "
        f"{agree}/{total}.",
        "",
        f"Label-adjusted clean (live): "
        f"{pct(adjusted_clean['rate'])} "
        f"({adjusted_clean['blocked']}/{adjusted_clean['cases']}"
        f"), Wilson 95% {adjusted_clean['wilson95']} — the "
        f"as-labelled rate is "
        f"{pct(as_labelled_clean['rate'])} "
        f"({as_labelled_clean['blocked']}/"
        f"{as_labelled_clean['cases']}); the gap is cases whose "
        f"only blockers are findings A1 adjudicated REAL "
        f"defects in mislabelled 'clean' code.",
        "",
        "## Prediction for the registered confirmation (§6.3)",
        "",
        f"- clean-BLOCKED: point "
        f"{pct(prediction['clean_BLOCKED_point'])}, 95% "
        f"interval {prediction['clean_BLOCKED_interval95']}",
        f"- recall (any severity): point "
        f"{pct(prediction['recall_any_severity_point'])}, 95% "
        f"interval "
        f"{prediction['recall_any_severity_interval95']}",
        f"- recall (blocking tier): point "
        f"{pct(prediction['recall_blocking_tier_point'])}, 95% "
        f"interval "
        f"{prediction['recall_blocking_tier_interval95']}",
        f"- merged blocking precision: point "
        f"{pct(prediction['merged_blocking_precision_point'])}",
        "",
        "Pilot bar (solution §6.2): clean-BLOCKED ≤ 0.20 on "
        "dev clean — see the live row (as-labelled and "
        "adjusted) above.",
        "",
    ]
    with open(os.path.join(HERE, "PILOT.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(json.dumps({"live_combined_clean": live["clean"],
                      "live_combined_defects": live["defects"],
                      "adjusted_clean": adjusted_clean,
                      "agreement": agreement,
                      "prediction": prediction}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
