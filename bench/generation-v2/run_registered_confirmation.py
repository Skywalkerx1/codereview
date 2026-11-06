#!/usr/bin/env python3
"""Registered Baseline v2 confirmation — generation-phase launcher
(pre-registration 2026-11-05 §1, as amended by Addendum A, in
force 2026-11-05: owner JCL + independent reviewer CC;
verify_registration exit 0 on master a808008).

Why this launcher exists instead of the stock
run_generation_v2.py CLI: the CLI derives its panel and binding
from the bench config, whose provider list is the v1 candidate
list [gemini, nvidia, openai, deepseek] with a DERIVED binding —
running it as-is would seat Gemini and put DeepSeek on the
operations lens, the S1 remap Addendum A item 9 declares
invalid. The registered run therefore drives bench/generation.py
directly with the registered composition stated explicitly:

  panel (config order): openai, nvidia, deepseek (Gemini
      preflighted for the record, never seated — registration
      §1 / v1 comparability, exactly as the voided driver did);
  seat_lenses (EXPLICIT, Addendum A item 9):
      openai -> [correctness], nvidia -> [operations],
      deepseek -> [correctness];
  fallbacks (Addendum A item 5): the correctness seats are each
      other's declared fallback; the machinery names one
      fallback seat per lens per run, and this run names
      "openai" — the panel's stable correctness seat — so a
      DeepSeek correctness failure is served by OpenAI. An
      OpenAI correctness failure has no second fallback in the
      machinery and is accounted under item 6, as is any
      operations failure (item 5 declares NO operations
      fallback; the lens is never re-seated);
  gate profile "balanced" (policy B1, SLOT-POLICY fill);
  call parameters: run_generation_v2.PARAMS verbatim (v1
      comparability), transports via run_generation_v2
      .build_transport; config identity (name + _config_sha)
      from the registered config, unchanged.

Sets: A5 holdout (bench/corpus split "holdout", 9 cases) +
expanded-clean stratum (35 cases, loaded with
run_confirmation_v2.load_expanded_clean, split "expanded-clean")
= 44 cases x 3 seats. Attempts consumed before this run: 0.
This is counting attempt 1 under the addendum.

Guard: refuses to run unless CODEREVIEW_REGISTERED_RUN=1.

Usage:
  run_registered_confirmation.py smoke
      One PUBLIC-split case through the identical machinery
      into throwaway /tmp dirs (wiring validation; touches no
      registered set).
  CODEREVIEW_REGISTERED_RUN=1 run_registered_confirmation.py run
      The registered generation pass (resumable; re-invoking
      resumes from the cache + records on disk).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(WORKTREE, "bench", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, os.path.join(WORKTREE, "bench"))
sys.path.insert(0, "/home/hatch/workspace/mitbbs-ai-swarm/agents")

# Bench runs draw DeepSeek on the dedicated bench key
# (run_generation_v2 sets this too; setdefault here so this
# entry point stands on its own).
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import generation as gen  # noqa: E402
import run_confirmation_v2 as conf  # noqa: E402
import run_generation_v2 as drv  # noqa: E402
import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402

PANEL = ["openai", "nvidia", "deepseek"]
BINDING = {"openai": ["correctness"], "nvidia": ["operations"],
           "deepseek": ["correctness"]}
FALLBACKS = {"correctness": "openai"}
ATTEMPT = 1


def build_seats():
    return {name: gen.GenerationSeat(
        name, panel_driver.MODELS[name], drv.build_transport(name),
        params=drv.PARAMS[name]) for name in PANEL}


def load_registered_cases():
    corpus = bench_mod.load_corpus(drv.CORPUS)
    holdout = [c for c in corpus if c["split"] == "holdout"]
    expanded = conf.load_expanded_clean()
    return holdout, expanded


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    cfg = bench_mod.load_config(drv.CONFIG_SPEC)
    cfg_sha = bench_mod._config_sha(cfg)
    drv.validate_fallbacks(FALLBACKS, PANEL, BINDING,
                           explicit=True)
    print(f"config: {cfg['name']} sha={cfg_sha}")
    print(f"panel (registered order): {PANEL}")
    print(f"seat_lenses (explicit): {BINDING}")
    print(f"fallbacks (pre-declared): {FALLBACKS}")

    if mode == "smoke":
        corpus = bench_mod.load_corpus(drv.CORPUS)
        pub = sorted((c for c in corpus if c["split"] == "public"),
                     key=lambda c: len(c["diff"]))
        cases = pub[:1]
        print(f"smoke case: {[c['id'] for c in cases]}")
        summary = gen.run_generation(
            cases, build_seats(), BINDING,
            cache_dir="/tmp/gen-smoke-cache",
            out_dir="/tmp/gen-smoke-out",
            config_name=cfg["name"], config_sha256=cfg_sha,
            attempt=ATTEMPT, fallbacks=FALLBACKS,
            gate_profile="balanced",
            allow_major=cfg["allow_major"], strict=cfg["strict"],
            seat_meta=cfg["seat_meta"] or None)
        print(json.dumps(summary, indent=1))
        return 0 if not summary["incomplete"] else 4

    if mode != "run":
        print(__doc__)
        return 2
    if os.environ.get("CODEREVIEW_REGISTERED_RUN") != "1":
        print("REFUSED: this is a registered set; generation "
              "against it runs only under Addendum A "
              "(CODEREVIEW_REGISTERED_RUN=1).", file=sys.stderr)
        return 2

    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    os.makedirs(drv.OUT_DIR, exist_ok=True)
    pf_path = os.path.join(
        drv.OUT_DIR, f"preflight-registered-{ATTEMPT}.json")
    with open(pf_path, "w", encoding="utf-8") as fh:
        json.dump({
            "attempt": ATTEMPT, "preflight": health,
            "gemini_seated": False,
            "gemini_exclusion": "not in the v1 panel; "
                                "comparability governs "
                                "(registration §1)",
            "panel": PANEL, "seat_lenses": BINDING,
            "fallbacks": FALLBACKS,
            "config": cfg["name"], "config_sha256": cfg_sha,
        }, fh, indent=1)
    dead = [n for n in PANEL if not (health.get(n) or {}).get("ok")]
    if dead:
        print(f"note: {dead} dead at preflight — they stay IN "
              f"the panel (S1); their cases record "
              f"unscored-infra and complete on a later resume.")
    holdout, expanded = load_registered_cases()
    cases = holdout + expanded
    print(f"cases: {len(holdout)} holdout + {len(expanded)} "
          f"expanded-clean = {len(cases)}")
    summary = gen.run_generation(
        cases, build_seats(), BINDING, cache_dir=drv.CACHE_DIR,
        out_dir=drv.OUT_DIR, config_name=cfg["name"],
        config_sha256=cfg_sha, attempt=ATTEMPT,
        fallbacks=FALLBACKS, gate_profile="balanced",
        allow_major=cfg["allow_major"], strict=cfg["strict"],
        seat_meta=cfg["seat_meta"] or None)
    print(json.dumps(summary, indent=1))
    return 0 if not summary["incomplete"] else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))
