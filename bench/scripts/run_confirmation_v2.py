#!/usr/bin/env python3
"""Baseline v2 confirmation driver (honest-negatives solution
step 7; pre-registration 2026-11-05 §1).

Runs the FROZEN policy B1 — gate profile `balanced`, filled into
SLOT-POLICY of the pre-registration before this driver first ran —
exactly once over the two confirmation sets:

  * the A5 private holdout (bench/corpus split `holdout`, 9 cases)
  * the expanded clean stratum (bench/expanded-clean, 35 cases)

The public split is NOT run: it was the exploration set.

Panel: the same seat composition as the 2026-11-04 baseline —
seat order [openai, nvidia, deepseek] (core assigns lenses by
seat order: correctness, operations, correctness), seats backed
by the swarm's llm_chain via run_panel_baseline's wrappers.
Every candidate family (including gemini) is preflighted first;
a panel family dead at preflight is excluded BEFORE the run and
documented. Gemini is excluded regardless of its preflight
result — it was not in the v1 panel, and comparability governs.

The stock bench runner has no gate-profile channel, so this
driver calls core.run_review directly with
gate_profile="balanced" (the top resolution source in step 6's
implementation) and otherwise mirrors bench.run_bench's record
construction field for field. Records land in
bench/confirmation-v2/attempt-<n>.jsonl, one attempt per file.

A run with any degraded case is VOID under the registration
(§1.5): the driver exits 3 and the attempt file is preserved as
evidence, never silently resumed or overwritten.

Usage:
  run_confirmation_v2.py preflight
  run_confirmation_v2.py run --attempt 1
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WORKTREE, "src"))

import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core  # noqa: E402

CONFIG_SPEC = panel_driver.CONFIG_SPEC
CORPUS = os.path.join(WORKTREE, "bench", "corpus")
EXPANDED = os.path.join(WORKTREE, "bench", "expanded-clean")
OUT_DIR = os.path.join(WORKTREE, "bench", "confirmation-v2")

# v1's seat order (bench/BASELINE-2026-11-04.md §2). Gemini is
# preflighted for the record but never seated (comparability).
PANEL = ["openai", "nvidia", "deepseek"]


def load_expanded_clean():
    """Load the expanded-clean stratum. bench.load_case rejects
    the `expanded-clean` split name (SPLITS is public/holdout),
    so the stratum is loaded here with the same field shape.
    Every case must be a clean control (expected == [])."""
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
        if meta.get("expected"):
            raise ValueError(f"{cid}: expanded-clean case carries "
                             f"expected defects — not a clean control")
        with open(os.path.join(case_dir, "diff.patch"),
                  encoding="utf-8", errors="replace") as fh:
            diff = fh.read()
        if not diff.strip():
            raise ValueError(f"{cid}: empty diff.patch")
        cases.append({
            "id": cid,
            "title": str(meta["title"]).strip(),
            "category": str(meta["category"]).strip(),
            "split": "expanded-clean",
            "context": str(meta.get("context") or ""),
            "expected": [],
            "diff": diff,
            "dir": case_dir,
        })
    return cases


def load_confirmation_cases():
    corpus = bench_mod.load_corpus(CORPUS)
    holdout = [c for c in corpus if c["split"] == "holdout"]
    expanded = load_expanded_clean()
    return holdout, expanded


def main(argv):
    mode = argv[1] if len(argv) > 1 else "preflight"
    attempt = 1
    if "--attempt" in argv:
        attempt = int(argv[argv.index("--attempt") + 1])
    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    os.makedirs(OUT_DIR, exist_ok=True)
    pf_path = os.path.join(OUT_DIR, f"preflight-attempt-{attempt}.json")
    with open(pf_path, "w", encoding="utf-8") as fh:
        json.dump({"attempt": attempt, "preflight": health,
                   "gemini_seated": False,
                   "gemini_exclusion": "not in the v1 panel; "
                   "comparability governs (registration §1 / step-7 "
                   "terms)"}, fh, indent=1)
    if mode == "preflight":
        return 0
    panel = [n for n in PANEL if (health.get(n) or {}).get("ok")]
    excluded = [n for n in PANEL if n not in panel]
    print(f"panel (seat order): {panel}")
    if excluded:
        print(f"excluded at preflight (dead): {excluded}")
    if os.environ.get("REQUIRE_FULL_PANEL") and panel != PANEL:
        # Operational gate (added after attempts 3–4, 2026-11-05):
        # the registered confirmation measures v1's exact seat
        # composition. A run missing a panel family — above all
        # NVIDIA, v1's sole operations family — measures a
        # different panel, so it must not start. A pre-run abort
        # under this gate is not an attempt: no case has run.
        print("ABORT (REQUIRE_FULL_PANEL): the full registered "
              f"panel {PANEL} is not healthy; no case has run, "
              f"this is not an attempt.", file=sys.stderr)
        return 2
    if len(panel) < 2:
        print("ABORT: fewer than two healthy panel families.",
              file=sys.stderr)
        return 2
    seats = {name: panel_driver.build_seat(name) for name in panel}
    cfg = bench_mod.load_config(CONFIG_SPEC)
    cfg_sha = bench_mod._config_sha(cfg)
    holdout, expanded = load_confirmation_cases()
    cases = holdout + expanded
    print(f"cases: {len(holdout)} holdout + {len(expanded)} "
          f"expanded-clean = {len(cases)}")
    out_path = os.path.join(OUT_DIR, f"attempt-{attempt}.jsonl")
    if os.path.exists(out_path):
        print(f"ABORT: {out_path} already exists — an attempt file "
              f"is evidence and is never overwritten.", file=sys.stderr)
        return 2
    degraded_cases = []
    with open(out_path, "w", encoding="utf-8") as fh:
        for case in cases:
            context = (f"[bench-case: {case['id']}]\n"
                       f"{case['title']}\n{case['context']}").strip()
            started = time.monotonic()
            report = core.run_review(
                case["diff"], seats, context=context,
                allow_major=cfg["allow_major"], strict=cfg["strict"],
                seat_meta=cfg["seat_meta"] or None,
                gate_profile="balanced")
            duration_ms = int((time.monotonic() - started) * 1000)
            calls = sum(int(r.get("attempts") or 1)
                        for r in report["reviewer_reports"])
            record = {
                "schema": bench_mod.RESULT_SCHEMA,
                "run": "baseline-v2-confirmation",
                "attempt": attempt,
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
                "duration_ms": duration_ms,
                "calls": calls,
                "cost_usd": 0.0,
                "patch_sha256": report["patch_sha256"],
                "findings": report["findings"],
                "reviewer_reports": [
                    {"provider": r["provider"], "lens": r["lens"],
                     "status": r["status"],
                     "attempts": r.get("attempts")}
                    for r in report["reviewer_reports"]],
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            print(f"[{case['split']}] {case['id']}: gate="
                  f"{record['gate']} degraded={record['degraded']} "
                  f"findings={len(record['findings'])} "
                  f"({duration_ms / 1000:.1f}s)", flush=True)
            if record["degraded"]:
                degraded_cases.append(case["id"])
    print(f"records: {len(cases)} -> {out_path}")
    if degraded_cases:
        print(f"VOID: {len(degraded_cases)} degraded case(s) "
              f"{degraded_cases} — under registration §1.5 this "
              f"attempt does not count; the file is preserved as "
              f"evidence.", file=sys.stderr)
        return 3
    print("attempt complete: zero degraded cases")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
