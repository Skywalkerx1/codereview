#!/usr/bin/env python3
"""Baseline panel driver for the Epic A benchmark (2026-11-04).

Runs bench config `panel-baseline-2026-11-04` over the PUBLIC split
with seats backed by the swarm's llm_chain (connector surrogate
credentials — no raw keys), injected via bench.run_bench's
providers_by_config, the same mechanism the internal review runner
uses. Seats mirror internal_review.py's wrappers (temperature 0.1,
json_mode, 240s timeout; NVIDIA at NVIDIA_MIN_TOKENS with no_think).

Panel selection: every candidate family is preflighted with one
tiny completion. The panel is built from the healthy families only,
interleaving lens priorities so correctness and operations each get
two families when the healthy set allows:
  correctness priority: gemini, openai, deepseek, nvidia
  operations  priority: nvidia, deepseek, openai, gemini
(core assigns lenses by seat order: seat 1 -> correctness,
seat 2 -> operations, seat 3 -> correctness, seat 4 -> operations.)

Usage:
  run_panel_baseline.py preflight   # probe all families, print JSON
  run_panel_baseline.py run [--force]  # preflight, then bench run
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
AGENTS = "/home/hatch/workspace/mitbbs-ai-swarm/agents"
sys.path.insert(0, AGENTS)
sys.path.insert(0, os.path.join(WORKTREE, "src"))

# Bench runs draw DeepSeek on the dedicated bench key, not the
# editorial key (llm_chain._deepseek_connector reads this at call
# time). setdefault: an operator-provided value wins.
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import llm_chain  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402

CONFIG_NAME = "panel-baseline-2026-11-04"
CORPUS = os.path.join(WORKTREE, "bench", "corpus")
CONFIG_SPEC = os.path.join(WORKTREE, "bench", "configs",
                           CONFIG_NAME + ".json")
OUT_DIR = os.path.join(WORKTREE, "bench-out")

def build_seat(name):
    """Return a prompt->text callable for one family, using the same
    call parameters as the internal review runner."""
    if name == "gemini":
        fn = lambda p: llm_chain.call_gemini(  # noqa: E731
            p, max_tokens=8192, temperature=0.1, json_mode=True,
            timeout=240)[0]
    elif name == "nvidia":
        fn = lambda p: llm_chain.call_nvidia(  # noqa: E731
            p, max_tokens=llm_chain.NVIDIA_MIN_TOKENS, temperature=0.1,
            json_mode=True, timeout=240, no_think=True)[0]
    elif name == "openai":
        fn = lambda p: llm_chain.call_openai(  # noqa: E731
            p, max_tokens=8192, temperature=0.1, json_mode=True,
            timeout=240)[0]
    elif name == "deepseek":
        fn = lambda p: llm_chain.call_deepseek(  # noqa: E731
            p, max_tokens=8192, temperature=0.1, json_mode=True,
            timeout=240)[0]
    else:
        raise ValueError(name)
    fn.__name__ = name
    return fn


MODELS = {
    "gemini": getattr(llm_chain, "GEMINI_MODEL", "gemini"),
    "nvidia": getattr(llm_chain, "NVIDIA_MODEL", "nvidia"),
    "openai": getattr(llm_chain, "OPENAI_MODEL", "openai"),
    "deepseek": getattr(llm_chain, "DEEPSEEK_MODEL", "deepseek"),
}

CORR_PRIORITY = ["gemini", "openai", "deepseek", "nvidia"]
OPS_PRIORITY = ["nvidia", "deepseek", "openai", "gemini"]


def preflight():
    """One tiny completion per family. Returns {name: result}."""
    probe = 'Reply with exactly this JSON object: {"ok": true}'
    results = {}
    for name in ("gemini", "nvidia", "openai", "deepseek"):
        entry = {"model": MODELS[name]}
        if name == "openai":
            entry["configured"] = bool(llm_chain.openai_configured())
        elif name == "deepseek":
            entry["configured"] = bool(llm_chain.deepseek_configured())
        started = time.monotonic()
        try:
            if name == "gemini":
                text, _u = llm_chain.call_gemini(
                    probe, max_tokens=256, temperature=0.0,
                    json_mode=True, timeout=90)
            elif name == "nvidia":
                text, _u = llm_chain.call_nvidia(
                    probe, max_tokens=llm_chain.NVIDIA_MIN_TOKENS,
                    temperature=0.0, json_mode=True, timeout=90,
                    no_think=True)
            elif name == "openai":
                text, _u = llm_chain.call_openai(
                    probe, max_tokens=256, temperature=0.0,
                    json_mode=True, timeout=90)
            else:
                text, _u = llm_chain.call_deepseek(
                    probe, max_tokens=256, temperature=0.0,
                    json_mode=True, timeout=90)
            entry["ok"] = bool(text and "ok" in text)
            entry["sample"] = (text or "")[:80]
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        entry["latency_s"] = round(time.monotonic() - started, 1)
        results[name] = entry
    return results


def choose_panel(healthy):
    """Interleave correctness/operations priorities over the healthy
    families: [corr#1, ops#1, corr#2, ops#2]."""
    corr = [n for n in CORR_PRIORITY if n in healthy]
    ops = [n for n in OPS_PRIORITY if n in healthy]
    panel = []
    for i in range(2):
        for pick in (corr, ops):
            if i < len(pick) and pick[i] not in panel:
                panel.append(pick[i])
    # Any healthy family not placed (cannot happen with <=4) appends.
    for n in healthy:
        if n not in panel:
            panel.append(n)
    return panel


def main(argv):
    mode = argv[1] if len(argv) > 1 else "preflight"
    health = preflight()
    print(json.dumps({"preflight": health}, indent=1))
    if mode == "preflight":
        return 0
    healthy = [n for n, r in health.items() if r.get("ok")]
    panel = choose_panel(set(healthy))
    print(f"healthy: {healthy}")
    print(f"panel (seat order): {panel}")
    if len(panel) < 2:
        print("ABORT: fewer than two healthy families — no viable "
              "two-family panel.", file=sys.stderr)
        return 2
    seats = {}
    for name in panel:
        seats[name] = build_seat(name)
    force = "--force" in argv
    results = bench_mod.run_bench(
        CORPUS, [CONFIG_SPEC], OUT_DIR, split="public", force=force,
        providers_by_config={CONFIG_NAME: seats})
    recs = results.get(CONFIG_NAME, [])
    gates = {}
    for r in recs:
        gates[r["gate"]] = gates.get(r["gate"], 0) + 1
    print(f"records: {len(recs)} gates: {gates}")
    print(f"results file: {os.path.join(OUT_DIR, CONFIG_NAME + '.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
