#!/usr/bin/env python3
"""B3 dev pilot — SCAFFOLDING runner (B3 design §8, 2026-11-06).

This runner exists to exercise the mechanism-agnostic pilot
harness (codereview.pilot) end to end on DEV data. It is NOT a
registered pilot: the B3 design is not yet owner-approved, no
prediction is computed or registered here, and the gate runs
under the CURRENT profiles only — there is no `reproduced`
profile, and nothing in this script creates one. What it does:

  * loads the design's dev case sets (the v1 public split +
    the expanded stratum with its A1 label amendments — the
    same sets the B2 dev pilot used);
  * writes the calibration/evaluation split manifest BEFORE
    anything runs (codereview.pilot.build_split_manifest);
  * runs the live pipeline once per case (panel = the v1
    baseline composition via run_panel_baseline, DeepSeek on
    the dedicated bench key), optionally with the probe channel
    wired (--probes: probe.make_probe_fn over each case's own
    directory — bench cases are diff-only, so probes execute
    against a temp copy of the case directory; outcomes are
    recorded as data and change no verdict);
  * emits the calibration table (codereview.pilot
    .build_calibration_table): per case, findings with
    eligibility + probe outcome, every current profile's
    replayed verdict, and the p_base / p_elig / p_settle
    factor INPUTS per slice. Inputs only — the registered
    prediction is a later, owner-approved step.

Usage:
  run_b3_pilot.py preflight
  run_b3_pilot.py run [--probes] [--out DIR]
                      [--live-profile strict|balanced|corroborated]
  run_b3_pilot.py table [--records PATH] [--out DIR]
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, os.path.join(WORKTREE, "bench"))

# Bench runs draw DeepSeek on the dedicated bench key.
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core, pilot as pilot_mod  # noqa: E402
from codereview import probe as probe_mod  # noqa: E402

CONFIG_SPEC = panel_driver.CONFIG_SPEC
CORPUS = os.path.join(WORKTREE, "bench", "corpus")
EXPANDED = os.path.join(WORKTREE, "bench", "expanded-clean")
DEFAULT_OUT = os.path.join(WORKTREE, "bench", "pilot-b3")
PANEL = ["openai", "nvidia", "deepseek"]
RUN_LABEL = "b3-dev-pilot-scaffold"


def load_expanded():
    """The expanded stratum with labels as they now stand
    (post-A1-amendment case.json files) — mirrors the B2 dev
    pilot's loader; bench.load_case cannot take these (their
    split values live outside bench.SPLITS)."""
    with open(os.path.join(EXPANDED, "manifest.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    listed = sorted(str(c.get("id") or "")
                    for c in manifest.get("cases") or [])
    cases = []
    for cid in listed:
        case_dir = os.path.join(EXPANDED, cid)
        with open(os.path.join(case_dir, "case.json"),
                  encoding="utf-8") as fh:
            meta = json.load(fh)
        if str(meta.get("id") or "") != cid:
            raise ValueError(f"{cid}: case.json id mismatch")
        with open(os.path.join(case_dir, "diff.patch"),
                  encoding="utf-8", errors="replace") as fh:
            diff = fh.read()
        if not diff.strip():
            raise ValueError(f"{cid}: empty diff.patch")
        # bench's own validator, so expected entries carry the
        # same normalized shape load_case produces.
        expected = [bench_mod._validate_expected(
            cid, e, os.path.join(case_dir, "case.json"))
            for e in meta.get("expected") or []]
        cases.append({
            "id": cid,
            "title": str(meta["title"]).strip(),
            "category": str(meta["category"]).strip(),
            "split": "expanded-clean" if not expected
                     else "expanded-defect",
            "source": str(meta.get("source") or "expanded"),
            "license": str(meta.get("license") or "n/a"),
            "context": str(meta.get("context") or ""),
            "expected": expected,
            "diff": diff,
            "dir": case_dir,
        })
    return cases


def load_dev_cases():
    corpus = bench_mod.load_corpus(CORPUS)
    public = [c for c in corpus if c["split"] == "public"]
    return public + load_expanded()


def family_map():
    cfg = bench_mod.load_config(CONFIG_SPEC)
    fam = {}
    for name, meta in (cfg["seat_meta"] or {}).items():
        fam[name] = (meta or {}).get("family") or "unknown"
    fam["deterministic"] = "deterministic"
    return fam


def cmd_preflight(_args):
    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    return 0


def cmd_run(args):
    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    panel = [n for n in PANEL if (health.get(n) or {}).get("ok")]
    if panel != PANEL:
        print(f"ABORT: pilot panel incomplete (healthy: {panel}); "
              f"a partial panel measures a different policy.",
              file=sys.stderr)
        return 2
    cases = load_dev_cases()
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    records_path = os.path.join(out_dir, "pilot-records.jsonl")
    if os.path.exists(records_path):
        print(f"ABORT: {records_path} already exists — pilot "
              f"records are evidence; remove deliberately to "
              f"re-run.", file=sys.stderr)
        return 2
    # The split is committed BEFORE anything runs (§8 step 1):
    # the manifest lands on disk first, and the table step
    # verifies the case set still matches it.
    manifest = pilot_mod.build_split_manifest(
        [c["id"] for c in cases])
    manifest_path = os.path.join(out_dir, "split-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"split: {len(manifest['calibration'])} calibration / "
          f"{len(manifest['evaluation'])} evaluation "
          f"(inputs sha256 {manifest['inputs_sha256'][:12]}…)")
    seats = {name: panel_driver.build_seat(name) for name in panel}
    cfg = bench_mod.load_config(CONFIG_SPEC)
    cfg_sha = bench_mod._config_sha(cfg)
    print(f"cases: {len(cases)} (dev sets) · live profile: "
          f"{args.live_profile} · probes: {args.probes}")
    with open(records_path, "w", encoding="utf-8") as fh:
        for case in cases:
            context = (f"[bench-case: {case['id']}]\n"
                       f"{case['title']}\n{case['context']}").strip()
            review_kwargs = {}
            if args.probes:
                review_kwargs["probe_fn"] = \
                    probe_mod.make_probe_fn(case["dir"])
            started = time.monotonic()
            report = core.run_review(
                case["diff"], seats, context=context,
                allow_major=cfg["allow_major"],
                strict=cfg["strict"],
                seat_meta=cfg["seat_meta"] or None,
                gate_profile=args.live_profile,
                **review_kwargs)
            duration_ms = int((time.monotonic() - started) * 1000)
            calls = sum(int(r.get("attempts") or 1)
                        for r in report["reviewer_reports"])
            record = {
                "schema": bench_mod.RESULT_SCHEMA,
                "run": RUN_LABEL,
                "config": cfg["name"],
                "config_sha256": cfg_sha,
                "case_id": case["id"],
                "split": case["split"],
                "category": case["category"],
                "created_at": core._now_iso(),
                "gate": report["gate"],
                "degraded": report["degraded"],
                "degraded_causes": report.get("degraded_causes"),
                "gate_profile": report["gate_profile"],
                "unverified_majors":
                    report.get("unverified_majors") or [],
                "duration_ms": duration_ms,
                "calls": calls,
                "cost_usd": 0.0,
                "patch_sha256": report["patch_sha256"],
                "findings": report["findings"],
                "reviewer_reports": [
                    core.reviewer_report_entry(r)
                    for r in report["reviewer_reports"]],
            }
            if review_kwargs:
                record["probes_enabled"] = True
                record["probe_outcomes"] = \
                    bench_mod._probe_outcomes(report)
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            print(f"[{case['split']}] {case['id']}: gate="
                  f"{record['gate']} degraded={record['degraded']} "
                  f"findings={len(record['findings'])} "
                  f"({duration_ms / 1000:.1f}s)", flush=True)
    print(f"records: {records_path}")
    return 0


def cmd_table(args):
    os.makedirs(args.out, exist_ok=True)
    records_path = args.records or os.path.join(
        args.out, "pilot-records.jsonl")
    records = []
    with open(records_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    cases = load_dev_cases()
    manifest = None
    manifest_path = os.path.join(args.out, "split-manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    table = pilot_mod.build_calibration_table(
        records, cases, family_map(), split_manifest=manifest)
    table_path = os.path.join(args.out, "calibration-table.json")
    with open(table_path, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, sort_keys=True)
    print(f"table: {table_path}")
    print(json.dumps({"cases": len(table["cases"]),
                      "factors": table["factors"]}, indent=1))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("preflight")
    run_ap = sub.add_parser("run")
    run_ap.add_argument("--probes", action="store_true",
                        help="wire the probe channel (data only; "
                             "no verdict changes)")
    run_ap.add_argument("--out", default=DEFAULT_OUT)
    run_ap.add_argument("--live-profile", default="strict",
                        choices=list(core.GATE_PROFILES),
                        help="profile the live run executes under; "
                             "all current profiles are replayed "
                             "into the table regardless")
    table_ap = sub.add_parser("table")
    table_ap.add_argument("--records", default=None,
                          help="records JSONL (default: "
                               "<out>/pilot-records.jsonl)")
    table_ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv[1:])
    if args.mode == "preflight":
        return cmd_preflight(args)
    if args.mode == "run":
        return cmd_run(args)
    return cmd_table(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
