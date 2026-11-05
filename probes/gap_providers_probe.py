"""Gap-pass probe — providers.py dispute cluster.

- 0e57186e8be8: agent spec parsing "breaks commands that contain
  colons" (split(':', 2) allegedly loses text after a 2nd colon).
  Check includes the ruling pack's P11 closure case verbatim.
- 1aec997aaec4 + 0ad4ed7db98e: api_names allegedly incomplete
  when the collision check runs (order dependence). Check: the
  ruling pack's P12 permutation + case-folding matrix over
  build_providers spec orders.
- 2242edbba9c9: os/signal allegedly not imported at module scope
  for _kill_tree. Check: module namespace + a functional
  process-group kill (P14 import guard, executed).

Writes results/gap-providers-cluster.txt. Facts only.
"""

import itertools
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import providers  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-providers-cluster.txt")


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("PROVIDERS CLUSTER PROBE — 0e57186e8be8 / 1aec997aaec4 / "
        "0ad4ed7db98e / 2242edbba9c9")
    say("")
    say("== 0e57186e8be8: agent spec colon handling "
        "(providers._parse_agent_spec) ==")
    colon_cases = [
        "agent:x:sh -c 'echo a:b'",                    # P11 closure case
        "agent:claude:run --flag http://x:8080/a:b",
        "agent:bot:echo one:two:three:four",
        "agent:my[home=private]:cmd --opt v:1",
    ]
    for spec in colon_cases:
        name, options, command = providers._parse_agent_spec(spec)
        say(f"  {spec!r}\n    -> name={name!r} options={options} "
            f"command={command!r}")
    _n, _o, cmd = providers._parse_agent_spec(colon_cases[1])
    say(f"  remainder after the 2nd colon preserved verbatim: "
        f"{cmd == 'run --flag http://x:8080/a:b'} "
        f"(split(':', 2) yields at most 3 parts; parts[2] is the "
        f"unsplit remainder)")

    say("")
    say("== 1aec997aaec4 + 0ad4ed7db98e: cross-kind collision, "
        "spec-order permutations (build_providers) ==")
    os.environ.setdefault("GAP_PROBE_KEY", "dummy-not-a-real-key")
    api_spec = "gemini"                       # preset API seat
    custom_spec = "myapi|openai|https://example.invalid/v1|m|GAP_PROBE_KEY"
    agent_spec = "agent:gemini:true"          # collides with preset
    agent_custom = "agent:myapi:true"         # collides with custom
    trials = []
    for order in itertools.permutations([agent_spec, api_spec]):
        trials.append(("agent 'gemini' vs preset 'gemini'",
                       list(order)))
    for order in itertools.permutations([agent_custom, custom_spec]):
        trials.append(("agent 'myapi' vs custom 'myapi'",
                       list(order)))
    trials.append(("case-fold: agent 'Gemini' vs preset 'gemini'",
                   ["agent:Gemini:true", "gemini"]))
    trials.append(("case-fold: agent 'gemini' vs preset 'Gemini'",
                   ["agent:gemini:true", "Gemini"]))
    trials.append(("no collision (control)",
                   ["agent:worker:true", "gemini"]))
    for label, specs in trials:
        try:
            built = providers.build_providers(specs)
            say(f"  {label}: specs={specs} -> BUILT {sorted(built)} "
                f"(no error)")
        except providers.ProviderError as exc:
            say(f"  {label}: specs={specs} -> ProviderError: "
                f"{str(exc)[:90]}")
    say("  (api_names is populated in a complete first pass over "
        "all non-agent specs — providers.py build_providers, the "
        "parse loop precedes the agent-finalization loop — so "
        "spec order cannot hide an API name from the check)")

    say("")
    say("== 2242edbba9c9: module-scope imports + _kill_tree ==")
    say(f"  'os' in providers module namespace: "
        f"{'os' in vars(providers)}; 'signal' in namespace: "
        f"{'signal' in vars(providers)}")
    say(f"  providers.os is the stdlib os module: "
        f"{providers.os is os}; providers.signal is stdlib "
        f"signal: {providers.signal is signal}")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    pgid = os.getpgid(proc.pid)
    providers._kill_tree(proc, pgid)
    deadline = time.monotonic() + 5
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    say(f"  functional kill: spawned sleeper pid={proc.pid} "
        f"pgid={pgid}; after _kill_tree, poll() -> {proc.poll()} "
        f"(SIGKILL = {-signal.SIGKILL})")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
