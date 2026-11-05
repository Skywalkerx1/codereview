#!/usr/bin/env python3
"""Generation-phase driver for the next confirmation attempt
(void solution §3.1, step 7 of its plan).

GENERATION ONLY: this driver produces the frozen response set —
per-case generation records plus scorer-format attempt records —
through bench/generation.py's cache + failure-class machinery.
Scoring is a separate, offline step with the committed scorer
(score_confirmation_v2.py), unchanged.

Differences from the voided run_confirmation_v2 driver:
  * seats are GenerationSeat wrappers: record/replay cache,
    per-call transport retries with backoff + jitter inside a
    per-job budget, first-valid-response caching;
  * the panel binding comes from the bench config's explicit
    seat_lenses (S1) — a seat dead at preflight is NOT dropped
    from the panel (that was the attempts 3–4 remap); its cases
    generate as unscored-infra and a later resume completes them
    when the seat is back;
  * per-lens fallback seats are pre-declared (§3.3): by default,
    for each lens, the first panel seat in config order that is
    not the lens's first bound seat (override with --fallbacks);
    the effective fallbacks are validated at entry against the
    panel and the seat_lenses binding and join the run's
    identity in the generation manifest;
  * cost is metered in tokens and shadow-priced (S4), never
    written as the $0 convention.

Registered-set guard: ONLY the public split is open. Every
other split — the A5 holdout, the expanded-clean stratum, and
any split a future loader learns — is a registered set and is
refused, before config load, preflight, or any seat call,
unless the environment variable CODEREVIEW_REGISTERED_RUN=1
is set; the registered run under Addendum A is what sets it.
Machinery work and smoke runs use the public split. The guard
is `registered_guard` below and refuses by split NAME, not by
which sets today's loader can reach, so a loader change cannot
silently open a registered set.

Usage:
  run_generation_v2.py [--split public] [--cases id,id]
                       [--out DIR] [--attempt N]
                       [--fallbacks '{"operations": "deepseek"}']
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

# Bench runs draw DeepSeek on the dedicated bench key, not the
# editorial key (llm_chain._deepseek_connector reads this at call
# time). setdefault: an operator-provided value wins.
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import llm_chain  # noqa: E402
import run_panel_baseline as panel_driver  # noqa: E402
import generation as gen  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core  # noqa: E402

CONFIG_SPEC = panel_driver.CONFIG_SPEC
CORPUS = os.path.join(WORKTREE, "bench", "corpus")
EXPANDED = os.path.join(WORKTREE, "bench", "expanded-clean")
OUT_DIR = os.path.join(WORKTREE, "bench", "generation-v2")
CACHE_DIR = os.path.join(WORKTREE, "bench", "generation-cache")

# Call parameters per family — the same parameters
# run_panel_baseline.build_seat uses (comparability with v1);
# they are part of every cache key via the params hash.
PARAMS = {
    "gemini": {"max_tokens": 8192, "temperature": 0.1,
               "json_mode": True, "timeout": 240},
    "openai": {"max_tokens": 8192, "temperature": 0.1,
               "json_mode": True, "timeout": 240},
    "deepseek": {"max_tokens": 8192, "temperature": 0.1,
                 "json_mode": True, "timeout": 240},
    "nvidia": {"max_tokens": llm_chain.NVIDIA_MIN_TOKENS,
               "temperature": 0.1, "json_mode": True,
               "timeout": 240, "no_think": True},
}


def build_transport(name):
    """prompt -> (text, usage): build_seat's calls, keeping the
    usage llm_chain returns so tokens can be metered (S4)."""
    fn = {"gemini": llm_chain.call_gemini,
          "nvidia": llm_chain.call_nvidia,
          "openai": llm_chain.call_openai,
          "deepseek": llm_chain.call_deepseek}[name]
    params = PARAMS[name]
    return lambda p: fn(p, **params)  # noqa: E731


def default_fallbacks(panel, binding):
    """Pre-declared per-lens fallbacks (§3.3): for each lens, the
    first panel seat in config order that is not the lens's first
    bound seat. Declared before the run and printed; a fallback
    that serves is recorded, never silent."""
    out = {}
    for lens in core.LENSES:
        bound = [s for s in panel if lens in binding.get(s, [])]
        for seat in panel:
            if seat not in bound:
                out[lens] = seat
                break
    return out


def registered_guard(split, registered):
    """The registered-set guard: a refusal message if generating
    `split` is not allowed, else None. Only "public" is open;
    every other split name is registered-only. The check is on
    the NAME, independent of what today's loader can load, so
    wiring a new corpus directory to a registered split cannot
    bypass it."""
    if split == "public" or registered:
        return None
    return (f"REFUSED: split {split!r} is a registered set; "
            f"generation against it runs only under Addendum A "
            f"(CODEREVIEW_REGISTERED_RUN=1).")


def validate_fallbacks(fallbacks, panel, binding, explicit=False):
    """Validate the effective per-lens fallbacks at driver entry
    (review minors on the S1 binding). Raises ValueError:

      * an unknown lens, or a fallback seat that is not in the
        panel — a fallback must name a declared panel seat;
      * under an EXPLICIT seat_lenses binding, a fallback that
        names, for a lens, a seat the binding does not bind to
        that lens while the lens is bound to other seat(s): the
        fallback would silently reassign the lens to a different
        seat — the S1 remap. (A fallback for a lens the binding
        leaves unbound is fine: it covers an otherwise unserved
        lens. Under a derived binding the historical
        order-based fallbacks stand, but panel membership is
        still enforced.)
    """
    for lens, seat in (fallbacks or {}).items():
        if lens not in core.LENSES:
            raise ValueError(
                f"fallbacks: unknown lens {lens!r} (known: "
                f"{', '.join(core.LENSES)})")
        if seat not in panel:
            raise ValueError(
                f"fallbacks: lens {lens!r} names seat {seat!r}, "
                f"which is not in the panel {list(panel)} — a "
                f"fallback must name a declared panel seat")
        if explicit:
            bound = {s for s, lenses in binding.items()
                     if lens in lenses}
            if bound and seat not in bound:
                raise ValueError(
                    f"fallbacks: lens {lens!r} is explicitly "
                    f"bound to {sorted(bound)} by seat_lenses, "
                    f"but its fallback names {seat!r} — a "
                    f"fallback may not reassign a lens the "
                    f"binding gives to a different seat (S1); "
                    f"declare the fallback from the lens's "
                    f"bound seats or amend the binding")


def main(argv):
    args = argv[1:]
    split = "public"
    if "--split" in args:
        split = args[args.index("--split") + 1]
    attempt = 1
    if "--attempt" in args:
        attempt = int(args[args.index("--attempt") + 1])
    out_dir = OUT_DIR
    if "--out" in args:
        out_dir = args[args.index("--out") + 1]
    only = None
    if "--cases" in args:
        only = {c.strip() for c in
                args[args.index("--cases") + 1].split(",")}
    registered = os.environ.get("CODEREVIEW_REGISTERED_RUN") == "1"
    refusal = registered_guard(split, registered)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    cfg = bench_mod.load_config(CONFIG_SPEC)
    cfg_sha = bench_mod._config_sha(cfg)
    panel = [n for n in bench_mod._provider_seat_names(
        cfg["providers"]) if n in PARAMS]
    binding = cfg["seat_lenses"]
    if "--fallbacks" in args:
        fallbacks = json.loads(args[args.index("--fallbacks") + 1])
    else:
        fallbacks = default_fallbacks(panel, binding)
    try:
        validate_fallbacks(
            fallbacks, panel, binding,
            explicit=cfg["seat_lenses_source"] == "explicit")
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"fallbacks (pre-declared): {fallbacks}")
    health = panel_driver.preflight()
    print(json.dumps({"preflight": health}, indent=1))
    print(f"panel (config order): {panel}")
    print(f"seat_lenses ({cfg['seat_lenses_source']}): {binding}")
    dead = [n for n in panel if not (health.get(n) or {}).get("ok")]
    if dead:
        print(f"note: {dead} dead at preflight — they stay IN "
              f"the panel (S1); their cases record unscored-infra "
              f"and complete on a later resume.")
    seats = {name: gen.GenerationSeat(
        name, panel_driver.MODELS[name], build_transport(name),
        params=PARAMS[name]) for name in panel}
    corpus = bench_mod.load_corpus(CORPUS)
    cases = [c for c in corpus if c["split"] == split]
    if only is not None:
        cases = [c for c in cases if c["id"] in only]
    print(f"cases: {len(cases)} ({split})")
    summary = gen.run_generation(
        cases, seats, binding, cache_dir=CACHE_DIR,
        out_dir=out_dir, config_name=cfg["name"],
        config_sha256=cfg_sha, attempt=attempt,
        fallbacks=fallbacks, gate_profile="balanced",
        allow_major=cfg["allow_major"], strict=cfg["strict"],
        seat_meta=cfg["seat_meta"] or None)
    print(json.dumps({k: v for k, v in summary.items()},
                     indent=1))
    return 0 if not summary["incomplete"] else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))
