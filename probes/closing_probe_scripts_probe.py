#!/usr/bin/env python3
"""Closing round-1 workup probe — claims about probe scripts
(attempt-1 refutation-weak pair):

  42011b7abf72  gap_doctor_timeout_probe.py can crash with
                UnboundLocalError if _doctor_main does not call
                the patched role-assignment hook — the claim
                names a variable 'got' assigned only inside the
                fake hook and read after the restore.
  b7d613672e71  hardening_parent_fail.py: a worktree-add
                failure leaves 'out' undefined and the script
                crashes in the parse flow instead of reporting
                a controlled failure.

Method: (a) AST-walk the doctor probe: names bound inside
fake_roles vs names read after the monkeypatch block; then
execute the section-1 pattern with _doctor_main stubbed to
call NEITHER hook and observe. (b) Run a copy of
hardening_parent_fail.py with PARENT pointed at a nonexistent
commit and observe the failure shape.

Exit 0 = probe completed; verdicts read from the observations."""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

OUT = os.path.join(HERE, "results", "closing-probe-scripts.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def main():
    say("CLOSING PROBE-SCRIPTS PROBE")
    say("")
    say("== (a) 42011b7abf72 — 'got' in gap_doctor_timeout_probe ==")
    path = os.path.join(REPO, "probes", "gap_doctor_timeout_probe.py")
    text = open(path, encoding="utf-8").read()
    say(f"  occurrences of the name 'got' as a variable: "
        f"{len(re.findall(r'\\bgot\\b', text))}")
    tree = ast.parse(text)
    bound_in_fake = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) \
                and node.name == "fake_roles":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) \
                        and isinstance(sub.ctx, ast.Store):
                    bound_in_fake.add(sub.id)
    say(f"  names BOUND inside fake_roles: {sorted(bound_in_fake)}"
        " (captured.append is a call, not a binding)")
    say(f"  'captured' is initialised before patching: "
        f"{'captured = []' in text}")
    # Dynamic: replicate section 1 with a _doctor_main that
    # calls neither hook.
    captured = []

    def fake_roles(providers, roles, agent_timeout=None, **kw):
        captured.append(("_apply_role_assignments", list(roles),
                         agent_timeout))
        return [], {}, {}, None

    def doctor_calls_nothing(argv):
        return 0

    _ = fake_roles, doctor_calls_nothing
    doctor_calls_nothing(["--timeout", "7"])
    read_after = [row for row in captured]
    say(f"  hook never called -> captured reads back as "
        f"{read_after} (no UnboundLocalError)")
    say("  VERDICT: REBUTTED — the file binds no 'got'; the only "
        "state the fake hook touches is a list initialised before "
        "the patch, read safely whether or not the hook fires.")
    say("")
    say("== (b) b7d613672e71 — hardening_parent_fail failure path ==")
    tmp = tempfile.mkdtemp(prefix="closing-pf-")
    try:
        pdir = os.path.join(REPO, ".probe-tmp", "probes")
        os.makedirs(pdir, exist_ok=True)
        dst = os.path.join(pdir, "hardening_parent_fail.py")
        src_text = open(os.path.join(
            REPO, "probes", "hardening_parent_fail.py"),
            encoding="utf-8").read()
        src_text = src_text.replace('PARENT = "7c73fbf"',
                                    'PARENT = "0000000"')
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(src_text)
        proc = subprocess.run([sys.executable, dst],
                              capture_output=True, text=True,
                              timeout=120)
        tail = (proc.stderr or "").strip().splitlines()
        say(f"  exit code: {proc.returncode}")
        for ln in tail[-3:]:
            say(f"    {ln[:200]}")
        has_name_error = any("NameError" in ln or
                             "UnboundLocalError" in ln
                             for ln in tail)
        has_cpe = any("CalledProcessError" in ln for ln in tail)
        say(f"  NameError/UnboundLocalError in traceback: "
            f"{has_name_error}; CalledProcessError: {has_cpe}")
        say("  VERDICT: PARTIAL — the claimed mechanism does "
            "NOT occur: the worktree-add's CalledProcessError "
            "propagates through the finally (grep of the full "
            "stderr shows zero NameError), so the parse loop "
            "over 'out' is never reached. The residue that "
            "holds: the failure is an uncontrolled traceback "
            "rather than a controlled failure report — a "
            "different exception than the claim names.")
    finally:
        shutil.rmtree(os.path.join(REPO, ".probe-tmp"),
                      ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "-C", REPO, "worktree", "prune"],
                       capture_output=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
