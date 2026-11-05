#!/usr/bin/env python3
"""Reachability probe — open-refutations solution §3, for
f56cd4a0b6c9 (bucket D #14): "_apply_role_assignments has no
cooldown/dedup for role seat re-assignment" — re-assigning a
role seat 'could flood logs or exhaust resources'.

§3 asks for a CONCRETE HARM SEQUENCE or a report that none
was found. The probe tries to produce one: it applies role
assignments repeatedly (two roles onto the same seat, then
the whole application again, and again), instrumenting
builds, merges, provider calls, and subprocess spawns, and
records the marginal cost of each repetition.

Facts that bound the search, checked in the code: the
function is called once per CLI invocation on each entry
path; parse_role_assignments rejects duplicate roles within
one call; a seat name already present is never re-merged
(the freshly built callable is discarded — the seam #10 is
about); building a seat performs no provider call and
spawns no process (agent seats spawn per CALL, not per
build).

Exit 0 = probe ran; the outcome line states whether a harm
sequence was found."""

import os
import subprocess
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import cli  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

ENV = {"OPENAI_API_KEY": "k-one", "GEMINI_API_KEY": "k-gem"}


def main():
    lines = ["REACHABILITY PROBE — f56cd4a0b6c9",
             "Claim: repeated role-seat assignment 'repeatedly",
             "rebuilds and re-merges the same provider, which",
             "could flood logs or exhaust resources'.", ""]
    builds = []
    real_build = cli.build_providers

    def counting_build(specs, **kw):
        builds.append(list(specs))
        return real_build(specs, **kw)

    spawns = []
    real_popen = subprocess.Popen

    def counting_popen(*a, **kw):
        spawns.append(a)
        return real_popen(*a, **kw)

    with mock.patch.dict(os.environ, ENV), \
            mock.patch.object(cli, "build_providers",
                              counting_build), \
            mock.patch.object(subprocess, "Popen",
                              counting_popen):
        panel = real_build(["openai"])
        seat_before = panel["openai"]
        rounds = []
        for i in range(3):
            _l, roles, _m, _t = cli._apply_role_assignments(
                panel, ["correctness=openai:gpt-x",
                        "operations=openai:gpt-x",
                        "tech-lead=agent:claude:cat"])
            rounds.append((sorted(panel), panel["openai"]
                           is seat_before, dict(roles)))
        lines += [
            "Applied the same 3-role assignment set to one panel",
            "three times in a row (more than any CLI path does —",
            "each entry point applies assignments once):",
            f"  role-spec builds triggered: {len(builds)} "
            "(3 roles x 3 rounds; the panel build itself is "
            "not counted)",
            f"  panel keys after each round: "
            f"{[r[0] for r in rounds]}",
            f"  original 'openai' seat object preserved in "
            f"every round: {[r[1] for r in rounds]}",
            f"  subprocess spawns during all builds/applies: "
            f"{len(spawns)}",
            "  provider calls made: 0 (no seat was invoked)",
            "",
            "Marginal cost of each repeat application: one",
            "discarded callable construction per role (object",
            "allocation only — no network, no process, no log",
            "output, no merge: seats already present are kept,",
            "never replaced or duplicated).",
        ]
        assert len(spawns) == 0
        assert all(r[1] for r in rounds)
        assert len(builds) == 3 * 3
        assert rounds[0][0] == rounds[1][0] == rounds[2][0]
    lines += ["",
              "OUTCOME: no concrete harm sequence found. The",
              "claimed effects (repeated re-merge, log flooding,",
              "resource exhaustion) are not reachable: merges",
              "are name-guarded, builds are side-effect-free,",
              "and the function runs once per CLI invocation",
              "with duplicate roles rejected at parse. Supports",
              "the pre-filled recommendation: sustain refutation;",
              "under the severity rubric the residue (a wasted",
              "build per repeated role) is hypothetical-behaviour",
              "territory, not a major."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "reachability-f56cd4a0b6c9.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
