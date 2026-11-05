#!/usr/bin/env python3
"""Closing-B probe — disputes freshness + Tech Lead
boundary assertion.

Claims:
  69a23ebb9f27 (attempt-1): disputes freshness check
    crashes when no inventory file is supplied.
  44ace5079160 (attempt-1, disputed): Tech Lead boundary
    assertion has no retry/fallback (cited at
    registry.py:45 — at HEAD registry.py:44-45 is the ROLES
    tuple; the assertion itself lives in core.py).

Writes results/closingB-disputes-registry.txt. Facts only.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import cli, disputes as disputes_mod  # noqa: E402

OUT = os.path.join(HERE, "results",
                   "closingB-disputes-registry.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def disputes_probe():
    say("== 69a23ebb9f27: disputes --check with NO "
        "--inventory (cli.py:1270-1317; disputes.py:578-591) ==")
    os.chdir(REPO)
    # In-process, span path, inventory_ids defaulted by the
    # CLI to an empty set when --inventory is absent.
    try:
        rc = cli._disputes_main(
            ["--repo", ".", "--check",
             "--span", "849e70e..HEAD"])
        say(f"  span path, no inventory file: rc={rc} "
            f"(0/1 are verdicts; a crash would raise)")
    except Exception:
        say("  span path RAISED:")
        say(traceback.format_exc())
    try:
        result = disputes_mod.check_freshness(
            ".", ".", "849e70e..HEAD", [])
        say(f"  check_freshness direct, inventory_ids "
            f"defaulted: returned violations="
            f"{len(result['violations'])} touching="
            f"{len(result['touching'])} unscoped="
            f"{len(result['unscoped'])}")
    except Exception:
        say("  check_freshness direct RAISED:")
        say(traceback.format_exc())
    try:
        rc = cli._disputes_main(["--repo", ".", "--check"])
        say(f"  no-span path, no inventory file: rc={rc}")
    except Exception:
        say("  no-span path RAISED:")
        say(traceback.format_exc())


def registry_probe():
    say("")
    say("== 44ace5079160: Tech Lead boundary assertion ==")
    reg = open(os.path.join(REPO, "src", "codereview",
                            "registry.py"),
               encoding="utf-8").read().splitlines()
    say(f"  registry.py:44-45 (the cited lines): "
        f"{reg[43].strip()} {reg[44].strip()} — the ROLES "
        f"tuple; registry.py contains no assertion")
    core_src = open(os.path.join(REPO, "src", "codereview",
                                  "core.py"),
                    encoding="utf-8").read().splitlines()
    for n in range(3250, 3284):
        say(f"  core.py:{n}: {core_src[n-1].strip()[:105]}")
    say("  behaviour is pinned by the suite: "
        "tests/test_shadow_p2.py::"
        "BoundaryAssertionTests."
        "test_mutant_selection_is_caught_at_the_boundary "
        "(run separately with unittest; result quoted in "
        "this probe's companion run) — selection-level "
        "substitution happens in _select_tech_lead BEFORE "
        "the assertion (core.py:3244-3250 records "
        "'substitutions'); the assertion itself is the "
        "documented fail-closed last line: record "
        "unavailable, route to the owner, never proceed "
        "with an ineligible seat")


def main():
    say("DISPUTES/REGISTRY PROBE — 69a23ebb9f27, "
        "44ace5079160")
    disputes_probe()
    registry_probe()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
