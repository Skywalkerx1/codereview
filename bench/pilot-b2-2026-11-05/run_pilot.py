#!/usr/bin/env python3
"""Policy B2 dev pilot (expert solution §6.2, Step 2+3).

Runs the LIVE product pipeline with gate profile `corroborated`
over DEV data only:

  * the v1 public split (bench/corpus, split "public":
    27 cases — 22 defect + 5 clean by original labels), and
  * the expanded stratum (bench/expanded-clean: 35 cases, all
    clean-labelled; the labels carry the dated 2026-11-05 A1
    amendments — 18 findings on 15 cases adjudicated REAL
    defects, recorded as case.json `label_amendments`; see
    label-amendments-2026-11-05.md).

This is NOT a registered run: no CODEREVIEW_REGISTERED_RUN, no
sealed material, no holdout. Panel = the v1 baseline composition
[openai, nvidia, deepseek] via run_panel_baseline's wrappers,
DeepSeek on the dedicated bench key. Every case runs ONCE under
`corroborated`; the paired strict/balanced/corroborated-replay
numbers are computed offline from the SAME stored responses by
score_pilot.py through the one evaluation entry point
(core.evaluate_gate_policy — §6.1, replay = live).

Usage:
  run_pilot.py preflight
  run_pilot.py run
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WORKTREE, "bench", "scripts"))
sys.path.insert(0, os.path.join(WORKTREE, "src"))

os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core  # noqa: E402

CONFIG_SPEC = panel_driver.CONFIG_SPEC
CORPUS = os.path.join(WORKTREE, "bench", "corpus")
EXPANDED = os.path.join(WORKTREE, "bench", "expanded-clean")
OUT_DIR = HERE
PANEL = ["openai", "nvidia", "deepseek"]


def load_expanded():
    """The expanded stratum with labels as they now stand
    (post-amendment case.json files). Stratum derives from the
    label: expected == [] -> expanded-clean, else
    expanded-defect."""
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
        expected = meta.get("expected") or []
        cases.append({
            "id": cid,
            "title": str(meta["title"]).strip(),
            "category": str(meta["category"]).strip(),
            "split": "expanded-clean" if not expected
                     else "expanded-defect",
            "context": str(meta.get("context") or ""),
            "expected": expected,
            "diff": diff,
            "dir": case_dir,
        })
    return cases


def main(argv):
    mode = argv[1] if len(argv) > 1 else "preflight"
    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    if mode == "preflight":
        return 0
    panel = [n for n in PANEL if (health.get(n) or {}).get("ok")]
    if panel != PANEL:
        print(f"ABORT: pilot panel incomplete (healthy: {panel}); "
              f"a partial panel measures a different policy.",
              file=sys.stderr)
        return 2
    seats = {name: panel_driver.build_seat(name) for name in panel}
    cfg = bench_mod.load_config(CONFIG_SPEC)
    cfg_sha = bench_mod._config_sha(cfg)
    corpus = bench_mod.load_corpus(CORPUS)
    public = [c for c in corpus if c["split"] == "public"]
    expanded = load_expanded()
    cases = public + expanded
    print(f"cases: {len(public)} public + {len(expanded)} "
          f"expanded = {len(cases)}")
    out_path = os.path.join(OUT_DIR, "pilot-records.jsonl")
    if os.path.exists(out_path):
        print(f"ABORT: {out_path} already exists — pilot records "
              f"are evidence; remove deliberately to re-run.",
              file=sys.stderr)
        return 2
    with open(out_path, "w", encoding="utf-8") as fh:
        for case in cases:
            context = (f"[bench-case: {case['id']}]\n"
                       f"{case['title']}\n{case['context']}").strip()
            started = time.monotonic()
            report = core.run_review(
                case["diff"], seats, context=context,
                allow_major=cfg["allow_major"],
                strict=cfg["strict"],
                seat_meta=cfg["seat_meta"] or None,
                gate_profile="corroborated")
            duration_ms = int((time.monotonic() - started) * 1000)
            calls = sum(int(r.get("attempts") or 1)
                        for r in report["reviewer_reports"])
            record = {
                "schema": bench_mod.RESULT_SCHEMA,
                "run": "b2-dev-pilot",
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
                    {"provider": r["provider"],
                     "lens": r["lens"],
                     "status": r["status"],
                     "attempts": r.get("attempts")}
                    for r in report["reviewer_reports"]],
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            print(f"[{case['split']}] {case['id']}: gate="
                  f"{record['gate']} degraded={record['degraded']} "
                  f"findings={len(record['findings'])} "
                  f"unverified={len(record['unverified_majors'])} "
                  f"({duration_ms / 1000:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
