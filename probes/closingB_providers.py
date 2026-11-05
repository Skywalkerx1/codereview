#!/usr/bin/env python3
"""Closing-B probe — providers.py cluster + intake timeout.

Claims:
  536112b7d4dd (attempt-1, disputed): agent subprocess
    inherits the full parent environment incl. provider
    keys.
  610a06422389 (attempt-1, disputed): agent timeout zero
    rejected as ProviderError — by design?
  ad6e36800a86 (attempt-1): configured intake solvers do
    not receive the requested timeout (trace
    _intake_main -> build_solvers at HEAD).

Writes results/closingB-providers.txt. Facts only.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import providers  # noqa: E402

OUT = os.path.join(HERE, "results", "closingB-providers.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


STUB = """import json, os, sys
keys = sorted(os.environ)
with open(%r, "w") as fh:
    json.dump(keys, fh)
print(json.dumps({"verdict": "pass", "summary": "stub",
                  "findings": []}))
"""

SLEEPER = """import time
time.sleep(30)
print("done")
"""


def main():
    say("PROVIDERS PROBE — 536112b7d4dd, 610a06422389, "
        "ad6e36800a86")
    td = tempfile.mkdtemp(prefix="closingB-prov-")
    dump = os.path.join(td, "envkeys.json")
    stub = os.path.join(td, "stub_agent.py")
    with open(stub, "w") as fh:
        fh.write(STUB % dump)
    os.environ["DUMP_PATH"] = dump
    os.environ["OPENAI_API_KEY"] = "sk-probe-secret-value"
    os.environ["GEMINI_API_KEY"] = "gemini-probe-secret"
    os.environ["CODEREVIEW_TEST_SECRET"] = "probe-secret"

    say("== 536112b7d4dd: agent env inheritance "
        "(providers.py:189-215, 316) ==")
    seat = providers.command_agent(f"{sys.executable} {stub}")
    seat("any prompt")
    import json
    keys = json.load(open(dump))
    leaked = [k for k in ("OPENAI_API_KEY", "GEMINI_API_KEY",
                          "CODEREVIEW_TEST_SECRET", "DUMP_PATH")
              if k in keys]
    say(f"  parent env carried OPENAI_API_KEY / "
        f"GEMINI_API_KEY / CODEREVIEW_TEST_SECRET / DUMP_PATH")
    say(f"  agent process env keys ({len(keys)}): {keys}")
    say(f"  secret keys present in agent env: {leaked}")
    os.environ["CODEREVIEW_AGENT_ENV"] = "CODEREVIEW_TEST_SECRET"
    try:
        providers.command_agent(f"{sys.executable} {stub}")("p")
        keys2 = json.load(open(dump))
        say(f"  with CODEREVIEW_AGENT_ENV=CODEREVIEW_TEST_SECRET "
            f"(documented opt-in): present="
            f"{'CODEREVIEW_TEST_SECRET' in keys2}; "
            f"OPENAI_API_KEY still absent="
            f"{'OPENAI_API_KEY' not in keys2}")
    finally:
        os.environ.pop("CODEREVIEW_AGENT_ENV", None)

    say("")
    say("== 610a06422389: agent timeout=0 "
        "(providers.py:288-293) ==")
    for t in (0, -5):
        try:
            providers.command_agent("true", timeout=t)
            say(f"  timeout={t}: accepted (no error)")
        except providers.ProviderError as exc:
            say(f"  timeout={t}: ProviderError at "
                f"construction — {exc}")
    try:
        providers.command_agent("true", timeout=None)
        say("  timeout=None: accepted (means AGENT_TIMEOUT "
            "default, per the docstring at providers.py:"
            "264-270)")
    except providers.ProviderError as exc:
        say(f"  timeout=None: ProviderError — {exc}")
    say("  docstring (providers.py:264-270): 'an explicit "
        "value is honored verbatim, and a non-positive value "
        "is refused HERE, at construction — never silently "
        "swapped for the default (review-v13 finding...)'")

    say("")
    say("== ad6e36800a86: intake solver timeout forwarding "
        "(cli.py:680 -> providers.build_solvers "
        "providers.py:753-763 -> build_providers -> "
        "command_agent) ==")
    sleeper = os.path.join(td, "sleeper.py")
    with open(sleeper, "w") as fh:
        fh.write(SLEEPER)
    solvers = providers.build_solvers(
        [f"agent:slow:{sys.executable} {sleeper}"],
        agent_timeout=1)
    name, fn = next(iter(solvers.items()))
    t0 = time.monotonic()
    try:
        fn("solve this")
        say("  solver returned without timing out "
            "(unexpected)")
    except providers.ProviderError as exc:
        say(f"  solver seat {name!r} with agent_timeout=1 "
            f"against a 30s sleeper: ProviderError after "
            f"{time.monotonic()-t0:.1f}s — {exc}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
