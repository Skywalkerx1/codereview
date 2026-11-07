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
    carries a verified non-interactive invocation (the spec's
    U6 rule: templates enter the table as build-phase probes
    verify them). Since Epic K2's U6 probe matrix, that is all
    three entries, each with its provenance class recorded at
    the entry: Claude Code (the shipped example wrapper,
    examples/agent-seat-claude.sh), Codex (invocation form
    verified live against codex-cli 0.164.0-alpha.9's own
    --help plus one logged-out exec probe, stdout contract
    from the official non-interactive docs), and Gemini CLI
    (official docs only — not installed on the build VM, so
    no live verification; the entry says so). A CLI whose
    invocation were still UNVERIFIED would be reported as
    found, with the reason it is not offerable; the user can
    still seat one by typing an agent: spec with their own
    command in the wizard's provider step, exactly as before
    this module existed.
  * Discovery reads the machine; it writes nothing. The wizard
    saves only what the user confirms, through the existing
    save path.
"""

from __future__ import annotations

import shutil
import subprocess
import threading

from . import hardening

PROBE_TIMEOUT = 5

# Retained-output ceiling for one --version probe (P3-07):
# a version string is one line; anything past this is a
# spewing binary, and the parent must not buffer it.
_PROBE_OUTPUT_CAP = 64 * 1024

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
        # U6 provenance: VERIFIED-LIVE for the invocation form
        # (`codex exec --help` on codex-cli 0.164.0-alpha.9,
        # plus one logged-out exec probe on the build VM that
        # consumed the piped prompt and attempted the call,
        # exiting 1 on 401s) and VERIFIED-DOCS for the contract
        # (developers.openai.com/codex/noninteractive: `-` /
        # piped stdin is the full prompt; only the final agent
        # message goes to stdout, progress to stderr; sandbox
        # defaults to read-only). `-s read-only` is stated
        # explicitly because a reviewer seat must never write;
        # `--skip-git-repo-check` because the seat's cwd is a
        # scratch dir, not a repo. An end-to-end SUCCESSFUL run
        # was not live-verified (no Codex login on the build
        # VM) — the form and failure behaviour are what U6
        # verified.
        "name": "codex",
        "display": "Codex",
        "binaries": ("codex",),
        "family": "openai",
        "command": "codex exec -s read-only "
                   "--skip-git-repo-check -",
    },
    {
        # U6 provenance: VERIFIED-DOCS only (Gemini CLI is not
        # installed on the build VM; nothing here is live-
        # verified). Official CLI reference (geminicli.com/
        # docs/cli/cli-reference): `-p/--prompt` "Appended to
        # stdin input if provided. Forces non-interactive
        # mode" — so the brief rides stdin exactly as with
        # Claude, and the -p text is the same seat instruction.
        # Headless reference documents exit codes 0 (success),
        # 1 (general/API failure), 42 (input error), 53 (turn
        # limit exceeded).
        "name": "gemini",
        "display": "Gemini CLI",
        "binaries": ("gemini",),
        "family": "google",
        "command": 'gemini -p "' + _CLAUDE_INSTRUCTION + '"',
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
    Used by the wizard's family warning and by providers'
    agent-seat family derivation (P6-06), which tries the
    seat command's program against the same table first."""
    entry = _BY_NAME.get(str(name).strip().lower())
    return entry["family"] if entry else None


def default_probe(path):
    """Cheap liveness probe: `<binary> --version`, bounded by
    PROBE_TIMEOUT, output capped. Returns (ok, detail) and never
    raises — a binary that cannot even answer --version is a
    probe failure with the reason attached, not an exception in
    the wizard."""
    # P3-04 backstop: the probed binary is a direct child of
    # this process (same /proc/$PPID/environ exposure as the
    # evidence sandbox's env-only mode).
    hardening.make_non_dumpable()
    # P3-07: the probe NEVER raises — not OSError, not a
    # timeout, not MemoryError from a spewing binary's
    # unbounded output (the old subprocess.run capture had
    # no cap, so the "never raises" contract was false).
    try:
        return _probe_version(path)
    except Exception as exc:  # noqa: BLE001 — never raises
        return False, f"could not run: {exc}"


def _drain_capped(stream, sink, proc):
    """Read `stream` into `sink` (a bytearray), retaining at
    most _PROBE_OUTPUT_CAP bytes; once the cap is exceeded,
    kill the child and keep draining (discarding) so the
    pipe never blocks it on the way down."""
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            room = _PROBE_OUTPUT_CAP - len(sink)
            if room >= len(chunk):
                sink.extend(chunk)
                continue
            if room > 0:
                sink.extend(chunk[:room])
            try:
                proc.kill()
            except OSError:
                pass
    except (OSError, ValueError):
        return


def _probe_version(path):
    proc = subprocess.Popen(
        [path, "--version"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    out_sink, err_sink = bytearray(), bytearray()
    readers = [
        threading.Thread(target=_drain_capped,
                         args=(proc.stdout, out_sink, proc),
                         daemon=True),
        threading.Thread(target=_drain_capped,
                         args=(proc.stderr, err_sink, proc),
                         daemon=True),
    ]
    for reader in readers:
        reader.start()
    return _supervise_probe_run(proc, readers, out_sink,
                                 err_sink)


def _supervise_probe_run(proc, readers, out_sink, err_sink):
    """The probe's supervised wait — the pairing the
    subprocess-timeout guard accepts by name, as it does the
    evidence sandbox's: every wait is deadline-bounded
    (wait(timeout=...), bounded joins) and expiry kills the
    child. It is a stronger bound than communicate(timeout=
    ...), not a weaker one: communicate buffers the child's
    output without bound, this wait drains it under the
    P3-07 cap."""
    try:
        proc.wait(timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()
        return False, (f"could not run: timed out after "
                       f"{PROBE_TIMEOUT} seconds")
    for reader in readers:
        reader.join(timeout=2)
    out = out_sink.decode("utf-8", "replace").strip() \
        or err_sink.decode("utf-8", "replace").strip()
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
        try:
            ok, detail = probe_fn(resolved)
        except Exception as exc:  # noqa: BLE001 — discovery
            # never raises (P3-07): a probe that blows up is
            # a failed probe with the reason attached.
            ok, detail = False, f"could not run: {exc}"
        found.append({**entry, "path": resolved,
                      "probe_ok": bool(ok),
                      "probe_detail": detail})
    return found
