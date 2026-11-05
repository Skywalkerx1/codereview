#!/usr/bin/env python3
"""codereview agent-CLI discovery — find the agent CLIs a user
already has installed, so first-run setup can offer them as
review seats (Epic K1).

The audience: users who run subscription-authenticated agent
CLIs (Claude Code, Codex, ...) and have no API keys. Agent seats
have existed since v0.7.0, but the setup wizard never looked at
the machine — a user had to know the agent:<name>:<command>
syntax and type a correct non-interactive invocation from
memory. Discovery closes that surface gap; it adds NO new
execution capability: a discovered seat is an ordinary agent
spec, executed, recorded, and probed exactly like a hand-typed
one.

Honesty rules (the reason this module is small):

  * A CLI is reported only when its binary is actually found on
    PATH (shutil.which semantics: present AND executable;
    directories and non-executable files do not count).
  * Each found binary gets a cheap `--version` probe. A failed
    probe is reported as failed, in those words — never smoothed
    over, never silently treated as working.
  * A seat command is pre-filled ONLY where this repository
    already carries a verified non-interactive invocation (the
    spec's U6 rule: templates enter the table as build-phase
    probes verify them). Today that is exactly one entry —
    Claude Code, whose invocation is the shipped example wrapper
    (examples/agent-seat-claude.sh). CLIs without a verified
    invocation are reported as found, with the reason they are
    not offerable; the user can still seat one by typing an
    agent: spec with their own command in the wizard's provider
    step, exactly as before this module existed.
  * Discovery reads the machine; it writes nothing. The wizard
    saves only what the user confirms, through the existing
    save path.
"""

from __future__ import annotations

import shutil
import subprocess

PROBE_TIMEOUT = 5

# The instruction the shipped example wrapper passes to Claude
# Code (examples/agent-seat-claude.sh, verbatim): the seat's
# brief arrives on stdin — command_agent pipes the prompt there
# AND names the same content's file in $CODEREVIEW_PROMPT, so
# the wrapper's `< "$CODEREVIEW_PROMPT"` redirect and this
# direct command receive identical input.
_CLAUDE_INSTRUCTION = (
    "You are a reviewer seat in a multi-model code review. "
    "The document on stdin is your complete brief: a diff plus "
    "instructions. Follow the instructions exactly and output "
    "ONLY the JSON verdict object they ask for — no prose, "
    "no markdown fences.")

# name        seat name (the agent:<name>:... the spec carries)
# display     human name for the offer lines
# binaries    candidate executable names, tried in order
# family      the CLI vendor's family tag — used ONLY by the
#             wizard's family-diversity warning. The gate tags
#             every agent seat family 'agent' (cli._default_
#             seat_meta) unless the operator overrides with
#             --seat-meta; discovery does not change that.
# command     the verified non-interactive invocation, or None
#             when this repository carries none (see module
#             docstring). Seat contract: the prompt arrives on
#             stdin and in $CODEREVIEW_PROMPT; stdout is the
#             response (providers.command_agent).
KNOWN_CLIS = (
    {
        "name": "claude",
        "display": "Claude Code",
        "binaries": ("claude",),
        "family": "anthropic",
        "command": 'claude -p --tools "" "' + _CLAUDE_INSTRUCTION
                   + '"',
    },
    {
        "name": "codex",
        "display": "Codex",
        "binaries": ("codex",),
        "family": "openai",
        "command": None,
    },
    {
        "name": "gemini",
        "display": "Gemini CLI",
        "binaries": ("gemini",),
        "family": "google",
        "command": None,
    },
)

_BY_NAME = {entry["name"]: entry for entry in KNOWN_CLIS}


def seat_spec(entry):
    """The ordinary agent spec a confirmed discovery pick saves
    (agent:<name>:<command>). Only callable for entries with a
    verified command — the wizard never offers the others."""
    if not entry.get("command"):
        raise ValueError(
            f"no verified seat command for {entry['name']!r}")
    return f"agent:{entry['name']}:{entry['command']}"


def family_for_seat_name(name):
    """Vendor family for an agent seat name, from the discovery
    table (agent:claude:* -> 'anthropic'); None for names the
    table does not know (a wrapper script, an echo stub, ...).
    Used by the wizard's family warning only — never by the
    gate, whose family tags come from cli seat metadata."""
    entry = _BY_NAME.get(str(name).strip().lower())
    return entry["family"] if entry else None


def default_probe(path):
    """Cheap liveness probe: `<binary> --version`, bounded by
    PROBE_TIMEOUT, output capped. Returns (ok, detail) and never
    raises — a binary that cannot even answer --version is a
    probe failure with the reason attached, not an exception in
    the wizard."""
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run: {exc}"
    out = (proc.stdout or proc.stderr or "").strip()
    detail = out.splitlines()[0][:120] if out else ""
    if proc.returncode != 0:
        return False, (f"exited {proc.returncode}"
                       + (f": {detail}" if detail else ""))
    return True, detail


def discover_clis(path_value=None, which_fn=None, probe_fn=None):
    """Scan PATH for the known agent CLIs.

    path_value: the PATH string to search (the wizard passes its
    environ's PATH); None means the process's own PATH. which_fn
    and probe_fn are injectable so tests fake the machine — no
    test may depend on the real PATH contents. Returns one dict
    per FOUND cli, in table order: the table entry plus 'path'
    (the resolved executable), 'probe_ok', and 'probe_detail'."""
    if which_fn is None:
        def which_fn(binary):
            return shutil.which(binary, path=path_value)
    if probe_fn is None:
        probe_fn = default_probe
    found = []
    for entry in KNOWN_CLIS:
        resolved = None
        for binary in entry["binaries"]:
            resolved = which_fn(binary)
            if resolved:
                break
        if not resolved:
            continue
        ok, detail = probe_fn(resolved)
        found.append({**entry, "path": resolved,
                      "probe_ok": bool(ok),
                      "probe_detail": detail})
    return found
