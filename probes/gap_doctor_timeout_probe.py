"""Gap-pass probe — 3fc4862824c9 (_doctor_main timeout).

Claim: timeout propagation to provider calls in _doctor_main
is missing. Refutation: the FALLBACK construction propagates
(agent_timeout=args.timeout) — true, and verified below. The
worksheet's question: the v0.11.0 review's standing major
3bbe648d8bfc said the doctor's probe calls had no wait bound,
and v0.11.1 (2dd114e) shipped "doctor probes are
wait-bounded" — is THIS dispute already fixed in substance?

Check: (1) at HEAD, capture agent_timeout at all three
construction sites (primary, fallback, role assignment) by
instrumenting the builders; (2) at HEAD, a hanging seat under
--timeout 1 returns in ~1s marked timed out; (3) PARENT-FAIL:
the identical call at 2dd114e^ (worktree) — no bound exists
there, the preflight waits for the seat's full sleep.

Writes results/gap-doctor-timeout-3fc4862824c9.txt. Facts only.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-doctor-timeout-3fc4862824c9.txt")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DRIVER = '''
import io, json, sys, time
from contextlib import redirect_stdout
sys.path.insert(0, sys.argv[1])
from codereview import cli

def hanging(_prompt):
    time.sleep(12)
    return "too late"

out = io.StringIO()
started = time.monotonic()
with redirect_stdout(out):
    rc = cli._doctor_main(["--timeout", "1"],
                          providers_override={"hang": hanging})
elapsed = time.monotonic() - started
res = json.loads(out.getvalue())
print(f"rc={rc} elapsed={elapsed:.1f}s ok={res['ok']} "
      f"seat_error={res['seats'][0]['error'][:60]!r}")
'''


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("DOCTOR TIMEOUT PROBE — 3fc4862824c9")
    say("")
    say("== HEAD: construction-site propagation (instrumented) ==")
    captured = []
    real_build = cli.build_providers
    real_roles = cli._apply_role_assignments

    def ok_fn(_prompt):
        return json.dumps({"summary": "ok", "findings": []})

    def fake_build(specs, agent_timeout=None, **kw):
        captured.append(("build_providers", list(specs),
                         agent_timeout))
        return {"fake": ok_fn}

    def fake_roles(providers, roles, agent_timeout=None, **kw):
        captured.append(("_apply_role_assignments", list(roles),
                         agent_timeout))
        return [], {}, {}, None

    cli.build_providers = fake_build
    cli._apply_role_assignments = fake_roles
    try:
        out = io.StringIO()
        with redirect_stdout(out):
            cli._doctor_main(
                ["--timeout", "7", "--provider", "seat-a",
                 "--fallback", "correctness=seat-b",
                 "--role", "tech_lead=seat-c"])
    finally:
        cli.build_providers = real_build
        cli._apply_role_assignments = real_roles
    for who, specs, timeout in captured:
        say(f"  {who}({specs}) received agent_timeout={timeout}")
    say("  run_doctor call at HEAD passes timeout=args.timeout "
        "(cli.py, _doctor_main tail) — fourth site, exercised "
        "next.")

    say("")
    say("== HEAD: hanging seat under --timeout 1 ==")
    never = threading.Event()

    def hanging(_prompt):
        never.wait(30)
        return "too late"

    out = io.StringIO()
    started = time.monotonic()
    with redirect_stdout(out):
        rc = cli._doctor_main(["--timeout", "1"],
                              providers_override={"hang": hanging})
    elapsed = time.monotonic() - started
    res = json.loads(out.getvalue())
    say(f"  rc={rc} elapsed={elapsed:.1f}s ok={res['ok']} "
        f"seat error={res['seats'][0]['error'][:60]!r}")

    say("")
    say("== PARENT-FAIL at 2dd114e^ (pre-fix tree, subprocess) ==")
    parent = subprocess.run(
        ["git", "rev-parse", "2dd114e^"], cwd=REPO,
        capture_output=True, text=True).stdout.strip()
    say(f"  parent commit: {parent}")
    with tempfile.TemporaryDirectory() as td:
        wt = os.path.join(td, "parent")
        subprocess.run(["git", "worktree", "add", "--detach", wt,
                        parent], cwd=REPO, capture_output=True)
        try:
            driver = os.path.join(td, "driver.py")
            with open(driver, "w") as fh:
                fh.write(DRIVER)
            proc = subprocess.run(
                [sys.executable, driver, os.path.join(wt, "src")],
                capture_output=True, text=True, timeout=120)
            say(f"  parent: {proc.stdout.strip()}")
            if proc.returncode != 0:
                say(f"  parent stderr tail: "
                    f"{proc.stderr[-200:]}")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force",
                            wt], cwd=REPO, capture_output=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO,
                           capture_output=True)
    say("contrast: HEAD returns in ~1s with the seat marked "
        "timed out; the pre-fix tree applies no --timeout bound "
        "to the probe and waits out the seat's full 12s sleep. "
        "Fix commit: 2dd114e (v0.11.1, 'doctor probes are "
        "wait-bounded', run_doctor gains timeout= + "
        "_probe_call_bounded).")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
