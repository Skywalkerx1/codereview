#!/usr/bin/env python3
"""Registered Policy B2 confirmation — generation-phase launcher
(pre-registration-b2-2026-11-05, signed 2026-11-06 by the owner
JCL and the independent reviewer CC; §13 signature fill).

Why this launcher exists instead of the stock
run_generation_v2.py CLI: the CLI derives its panel and binding
from the bench config, whose provider list is the v1 candidate
list [gemini, nvidia, openai, deepseek] with a DERIVED binding —
running it as-is would seat Gemini and put DeepSeek on the
operations lens, the S1 remap Addendum A item 9 declares
invalid. Exactly as the attempt-1 registered launcher did, this
driver drives bench/generation.py directly with the registered
composition stated explicitly:

  panel (config order): openai, nvidia, deepseek (Gemini
      preflighted for the record, never seated — it was not in
      the v1 panel and comparability governs);
  seat_lenses (EXPLICIT, Addendum A item 9 via registration §7):
      openai -> [correctness], nvidia -> [operations],
      deepseek -> [correctness];
  fallbacks (Addendum A item 5, carried over by registration
      §7): the correctness seats are each other's declared
      fallback; the machinery names one fallback seat per lens
      per run, and this run names "openai" — the panel's stable
      correctness seat — so a DeepSeek correctness failure is
      served by OpenAI. An OpenAI correctness failure has no
      second fallback in the machinery and is accounted under
      the §5 cap, as is any operations failure (item 5 declares
      NO operations fallback; the lens is never re-seated);
  gate profile "corroborated" (Policy B2, registration §2 —
      frozen code state a88df64, core.py sha256 afe6bc2e...);
  call parameters: run_generation_v2.PARAMS verbatim (v1
      comparability), transports via run_generation_v2
      .build_transport; config identity (name + _config_sha)
      from the registered config, unchanged.

Sets: bench/generation-v3 — all 88 cases (clean 64 = 56
authored + 8 real-world; defects 24 = 14 injected + 10
real-world), loaded with bench.load_corpus; the per-case
`stratum` field is read from each case.json and preserved into
every record (registration §8(a)). Seal: SEALED-MANIFEST.json
sha256 35bea802... at source commit 0e3bf46. Attempts on these
sets before this run: 0. This is counting attempt 1 under the
registration.

Generation/scoring separation (registration §7): this driver
is the GENERATION half. Scoring is the separate, offline step
(score_confirmation_v2.py, score_attempt_v3), run once
generation is complete. A case whose seats never serve stays
incomplete here and is accounted as unscored by the scorer —
at most 4 of 88 unscored + corroboration-unavailable cases are
tolerated; beyond that the run is VOID (registration §5/§9).

Guard: refuses to run unless CODEREVIEW_REGISTERED_RUN=1.

Usage:
  run_confirmation_b2.py preflight
      Probe all families, print JSON (no generation).
  run_confirmation_b2.py smoke
      One PUBLIC-split case through the identical machinery
      into throwaway /tmp dirs (wiring validation; touches no
      registered set).
  CODEREVIEW_REGISTERED_RUN=1 run_confirmation_b2.py run
      The registered generation pass (resumable; re-invoking
      resumes from the cache + records on disk).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, os.path.join(WORKTREE, "bench"))
sys.path.insert(0, "/home/hatch/workspace/mitbbs-ai-swarm/agents")

# Bench runs draw DeepSeek on the dedicated bench key
# (run_generation_v2 sets this too; setdefault here so this
# entry point stands on its own).
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import generation as gen  # noqa: E402
import run_generation_v2 as drv  # noqa: E402
import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402

PANEL = ["openai", "nvidia", "deepseek"]
BINDING = {"openai": ["correctness"], "nvidia": ["operations"],
           "deepseek": ["correctness"]}
FALLBACKS = {"correctness": "openai"}
ATTEMPT = 1
GEN3 = os.path.join(WORKTREE, "bench", "generation-v3")
OUT_DIR = os.path.join(WORKTREE, "bench", "confirmation-b2")
CACHE_DIR = os.path.join(OUT_DIR, "cache")

EXPECTED_STRATA = {"clean-authored": 56, "clean-realworld": 8,
                   "defect-injected": 14, "defect-realworld": 10}


def build_seats():
    return {name: gen.GenerationSeat(
        name, panel_driver.MODELS[name], drv.build_transport(name),
        params=drv.PARAMS[name]) for name in PANEL}


def load_gen3_cases():
    """All 88 generation-v3 cases with `stratum` injected from
    each case.json (bench.load_case does not carry the field;
    registration §8(a) requires it preserved into records).
    Strata counts are asserted against the seal — a mismatch is
    a loud stop, never a partial run."""
    cases = bench_mod.load_corpus(GEN3)
    if len(cases) != 88:
        raise ValueError(
            f"generation-v3: expected 88 cases, loaded "
            f"{len(cases)}")
    counts = {}
    for case in cases:
        with open(os.path.join(case["dir"], "case.json"),
                  encoding="utf-8") as fh:
            meta = json.load(fh)
        stratum = meta.get("stratum")
        if not stratum:
            raise ValueError(
                f"{case['id']}: case.json carries no stratum")
        case["stratum"] = stratum
        counts[stratum] = counts.get(stratum, 0) + 1
        if case["split"] != "holdout":
            raise ValueError(
                f"{case['id']}: split {case['split']!r} != "
                f"'holdout'")
    if counts != EXPECTED_STRATA:
        raise ValueError(
            f"generation-v3 strata mismatch: {counts} != "
            f"{EXPECTED_STRATA} (sealed counts)")
    return cases


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

    if mode == "preflight":
        health = panel_driver.preflight()
        print(json.dumps({"preflight": health}, indent=1))
        return 0

    if mode == "smoke":
        corpus = bench_mod.load_corpus(drv.CORPUS)
        pub = sorted((c for c in corpus if c["split"] == "public"),
                     key=lambda c: len(c["diff"]))
        cases = pub[:1]
        print(f"smoke case: {[c['id'] for c in cases]}")
        summary = gen.run_generation(
            cases, build_seats(), BINDING,
            cache_dir="/tmp/gen-b2-smoke-cache",
            out_dir="/tmp/gen-b2-smoke-out",
            config_name=cfg["name"], config_sha256=cfg_sha,
            attempt=ATTEMPT, run_label="b2-confirmation",
            fallbacks=FALLBACKS, gate_profile="corroborated",
            allow_major=cfg["allow_major"], strict=cfg["strict"],
            seat_meta=cfg["seat_meta"] or None)
        print(json.dumps(summary, indent=1))
        return 0 if not summary["incomplete"] else 4

    if mode != "run":
        print(__doc__)
        return 2
    if os.environ.get("CODEREVIEW_REGISTERED_RUN") != "1":
        print("REFUSED: this is a registered set; generation "
              "against it runs only under the signed B2 "
              "registration (CODEREVIEW_REGISTERED_RUN=1).",
              file=sys.stderr)
        return 2

    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    os.makedirs(OUT_DIR, exist_ok=True)
    pf_path = os.path.join(
        OUT_DIR, f"preflight-registered-{ATTEMPT}.json")
    if not os.path.exists(pf_path):
        with open(pf_path, "w", encoding="utf-8") as fh:
            json.dump({
                "attempt": ATTEMPT, "preflight": health,
                "gemini_seated": False,
                "gemini_exclusion": "not in the v1 panel; "
                                    "comparability governs "
                                    "(registration §2)",
                "panel": PANEL, "seat_lenses": BINDING,
                "fallbacks": FALLBACKS,
                "config": cfg["name"], "config_sha256": cfg_sha,
                "gate_profile": "corroborated",
                "sets": "bench/generation-v3 (seal 35bea802..., "
                        "source commit 0e3bf46)",
            }, fh, indent=1)
    dead = [n for n in PANEL if not (health.get(n) or {}).get("ok")]
    if dead:
        print(f"note: {dead} dead at preflight — they stay IN "
              f"the panel (S1); their cases record unscored-infra "
              f"and complete on a later resume.")
    cases = load_gen3_cases()
    print(f"cases: {len(cases)} (generation-v3, all strata)")
    summary = gen.run_generation(
        cases, build_seats(), BINDING, cache_dir=CACHE_DIR,
        out_dir=OUT_DIR, config_name=cfg["name"],
        config_sha256=cfg_sha, attempt=ATTEMPT,
        run_label="b2-confirmation",
        fallbacks=FALLBACKS, gate_profile="corroborated",
        allow_major=cfg["allow_major"], strict=cfg["strict"],
        seat_meta=cfg["seat_meta"] or None)
    print(json.dumps(summary, indent=1))
    return 0 if not summary["incomplete"] else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))
