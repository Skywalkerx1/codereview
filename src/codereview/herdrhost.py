#!/usr/bin/env python3
"""codereview herdr pane hosting (Epic K3a) — an OPTIONAL
transport for agent seats the user already configured.

Herdr (github.com/herdrdev/herdr) is a terminal runtime that
hosts coding-agent CLIs in supervised panes. A seat whose name
is listed under `[hosting] herdr = [...]` in the saved user
config may run inside a herdr pane instead of a headless
subprocess, so the user can watch (and intervene in) the run
from herdr's UI. Nothing else changes: same spec, same prompt
contract, same record discipline, same gate. Herdr never
becomes a hard dependency — with herdr absent, too old, or
schema-mismatched, the adapter is inert, the seats run
headless exactly as before, and the run record carries one
line saying why (the CLI puts it in `herdr_hosting` via
record_extra).

Binding layer: herdr's CLI wrappers only (`herdr workspace
create`, `herdr pane run`, `herdr pane get`, `herdr api
snapshot`, ...). Raw socket access is a separate later
decision, per the K spec. Two surface choices worth stating:

  * The seat is launched with `pane run`, not `agent start`.
    `agent start` launches a RECOGNISED agent kind for
    interactive prompting; a CodeReview seat is a one-shot
    command with a file/stdin/stdout contract, which is
    exactly what herdr's own automation docs assign to pane
    commands ("shells, tests, servers, CI watchers, and other
    ordinary terminal processes"). The packet itself is never
    typed: the pane command line redirects stdin FROM the
    prompt file and names it in $CODEREVIEW_PROMPT (passed
    via `workspace create --env`, never typed either) — the
    same contract the headless runner gives the seat.
  * There is no `events` CLI in herdr: events.subscribe /
    events.wait exist only on the socket API. The wrapper-
    layer subscription is therefore a supervised watch —
    repeated `pane get` polls standing in for
    pane.agent_status_changed / pane.exited — and any break
    in that watch (a failed poll, a vanished pane) is treated
    as the socket layer's `events_lost`: reconcile ONCE via
    `herdr api snapshot` (session.snapshot), then continue
    only if the snapshot shows the same pane with the same
    terminal_id. A pane that is gone, or whose terminal_id
    changed (herdr restarted and restored layout — a resumed
    session whose in-flight context cannot be proven
    identical, spec U5), is a recorded seat failure. There is
    no silent resume, ever: the adapter never re-creates a
    pane or re-runs a command inside an attempt.

Truth seniority (K spec §5.1, K2 §4.2): the seat's outcome is
decided by OUR files — the capture files and the exit-code
file the pane command writes — exactly as the headless runner
decides from its subprocess. Herdr's agent_status is signal
#4, advisory only: it is recorded in the run's hosting
receipt and may surface an advisory blocked:input episode in
the seat-state trace while the seat runs; it never raises,
clears, or re-weights a finding, and when it disagrees with
the files, the files win and the disagreement stays in the
receipt's observations.

Environment discipline (spec U7): the pane is the user's own
terminal session — herdr injects its HERDR_* variables and
the user's shell environment applies. We add exactly one
variable of our own, CODEREVIEW_PROMPT (a path, not a
secret), plus HOME when the seat spec says home=private.
Operator API keys are never added to a pane: the headless
allow-list exists so keys stay out of agent processes, and
hosting does not smuggle them back in through the terminal.

Version discipline: the adapter feature-detects against
`herdr api schema --json` (the method and event names below
must all be present) and enforces MIN_HERDR_VERSION. The
floor and the name list are set from the herdr tree inspected
at build time (0.9.5, protocol 22); U8's cross-release schema
diff could not be run from a single clone, so the floor is
the oldest 0.9.x line and the schema check does the real
work on every run.

Live-smoke status: UNVERIFIED on the build machine — no real
herdr is installed there (and no Rust toolchain to build
one). The full lifecycle is tested against a stub `herdr`
executable implementing the used CLI surface; a real-herdr
smoke remains an open verification item, recorded as such in
the changelog.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import shutil
import subprocess

# Oldest herdr the adapter will drive (see module docstring).
MIN_HERDR_VERSION = (0, 9, 0)

# The socket methods the used CLI wrappers stand on, and the
# event types the wrapper-layer watch stands in for. All must
# appear in `herdr api schema --json`; a herdr missing any of
# them is a schema mismatch and the adapter stays inert.
REQUIRED_METHODS = (
    "workspace.create", "workspace.close",
    "pane.get", "pane.close", "pane.send_input",
    "agent.get", "session.snapshot",
)
REQUIRED_EVENTS = ("pane.agent_status_changed", "pane.exited")

# Bound on a single herdr CLI call (seconds). The seat's own
# timeout bounds the run; these calls are control-plane only.
CLI_TIMEOUT = 15

# The current job's hosting-receipt box (a list), installed by
# core._review_job exactly as seatstate.CURRENT is: a hosted
# seat callable appends one receipt per attempt, and the job
# owner attaches the LAST one (the determining attempt's) to
# the result as `hosting`. ContextVar so concurrent jobs on
# pooled threads never share a box. Default None: no box, no
# receipts — headless runs are untouched.
RECEIPTS = contextvars.ContextVar(
    "codereview_herdr_receipts", default=None)


class HerdrError(Exception):
    """One herdr CLI call failed (exit != 0, timeout, or
    unparseable output). The message carries the herdr stderr
    tail when there is one — recorded, never invented."""


def parse_version(text):
    """'herdr 0.9.5' / '0.9.5-preview.123' -> (0, 9, 5);
    None when no dotted triple is present."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def version_str(version):
    return ".".join(str(n) for n in version)


def schema_names(schema_text):
    """All method/event names a schema document mentions.
    Walks every string in the parsed JSON (method names live
    under `schemas.request`, event names under
    `schemas.event` / `schemas.subscription_event`, but the
    walk does not depend on that layout — a schema that
    reorganises its sections still feature-detects)."""
    try:
        doc = json.loads(schema_text)
    except (ValueError, TypeError, RecursionError):
        return set()
    names = set()
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str) and re.fullmatch(
                r"[a-z_]+\.[a-z_]+", node):
            names.add(node)
    return names


def _default_run(argv, timeout):
    """(returncode, stdout, stderr) for one herdr CLI call.
    A timeout or a missing binary is returncode -1 with the
    reason on stderr — callers turn it into HerdrError."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except OSError as exc:
        return -1, "", f"could not run: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


class HerdrHost:
    """A detected, feature-checked herdr session, driven
    through its CLI. One instance serves a whole run; every
    hosted seat attempt creates and closes its own workspace
    (labelled, so leftovers are recognisable)."""

    def __init__(self, binary, version, run_fn=None):
        self.binary = binary
        self.version = version  # tuple, e.g. (0, 9, 5)
        self._run = run_fn or _default_run

    @property
    def version_text(self):
        return version_str(self.version)

    def _cli(self, args, timeout=CLI_TIMEOUT):
        rc, out, err = self._run([self.binary, *args], timeout)
        if rc != 0:
            tail = (err or out).strip()[-300:]
            raise HerdrError(
                f"herdr {' '.join(args[:2])} exited {rc}"
                + (f": {tail}" if tail else ""))
        return out

    def _cli_json(self, args, timeout=CLI_TIMEOUT):
        out = self._cli(args, timeout=timeout)
        try:
            doc = json.loads(out)
        except (ValueError, RecursionError) as exc:
            # RecursionError: output nested past the
            # interpreter limit is unparseable for our
            # purposes (P3-08), not a crash in the caller.
            raise HerdrError(
                f"herdr {' '.join(args[:2])} returned "
                f"unparseable output: {exc}") from exc
        if not isinstance(doc, dict):
            # Every consumer of this helper calls .get on the
            # result; a bare list/null/scalar is a malformed
            # envelope and must fail as HerdrError (which
            # detect() turns inert), never as AttributeError
            # in snapshot()/create_workspace()/pane_get().
            raise HerdrError(
                f"herdr {' '.join(args[:2])} returned a "
                f"non-object document "
                f"({type(doc).__name__})")
        if "error" in doc:
            raise HerdrError(
                f"herdr {' '.join(args[:2])} reported "
                f"{str(doc['error'])[:300]}")
        # CLI responses are envelopes ({"id":..., "result":{...}});
        # accept a bare payload too, so a wrapper that prints the
        # result directly still binds.
        if isinstance(doc.get("result"), dict):
            return doc["result"]
        return doc

    # -- session ------------------------------------------------
    def snapshot(self):
        """session.snapshot -> the snapshot dict (workspaces,
        tabs, panes, agents). Reconciliation source of truth
        after any watch break."""
        result = self._cli_json(["api", "snapshot"])
        snap = result.get("snapshot")
        return snap if isinstance(snap, dict) else result

    # -- panes --------------------------------------------------
    def create_workspace(self, cwd, label, env=None):
        """-> (workspace_id, pane_id) for a fresh CodeReview
        workspace whose root pane sits in `cwd`. `env` rides
        herdr's own --env (the launched process's environment)
        — values are never typed into the pane."""
        args = ["workspace", "create", "--cwd", cwd,
                "--label", label, "--no-focus"]
        for key in sorted((env or {})):
            args += ["--env", f"{key}={env[key]}"]
        result = self._cli_json(args)
        pane = result.get("root_pane") or {}
        workspace = result.get("workspace") or {}
        pane_id = pane.get("pane_id")
        workspace_id = workspace.get("workspace_id")
        if not pane_id or not workspace_id:
            if workspace_id:
                # Half-created: the workspace exists server-
                # side and this id is the only handle anyone
                # will ever have on it — close it now rather
                # than leak it.
                try:
                    self.close_workspace(workspace_id)
                except HerdrError:
                    pass
            raise HerdrError(
                "herdr workspace create returned no "
                "root_pane/workspace ids")
        return workspace_id, pane_id

    def pane_run(self, pane_id, command_line):
        """Submit one command line to the pane's shell
        (pane.send_input under the wrapper; quiet on success).
        The line is a launcher for the seat command — the
        review packet itself is never in it (it travels by
        file; see the module docstring)."""
        self._cli(["pane", "run", pane_id, command_line])

    def pane_get(self, pane_id):
        """-> the PaneInfo dict for `pane_id`, or None when
        herdr answers cleanly that no such pane exists.
        Transport failures raise HerdrError."""
        result = self._cli_json(["pane", "get", pane_id])
        pane = result.get("pane")
        return pane if isinstance(pane, dict) else result

    def close_workspace(self, workspace_id):
        self._cli(["workspace", "close", workspace_id])

    def close_pane(self, pane_id):
        self._cli(["pane", "close", pane_id])


def detect(environ=None, which_fn=None, run_fn=None):
    """Probe the machine for a usable herdr, in the spec's
    order: on PATH -> version floor -> schema feature-detect
    -> reachable session. Returns a plan dict:

        {"active": True,  "host": HerdrHost, "version": (x,y,z),
         "reason": None}
        {"active": False, "host": None, "version": ... or None,
         "reason": "<one line, recorded verbatim in the record>"}

    `environ` is accepted for symmetry with userconfig (the
    probe reads HERDR_SOCKET_PATH's presence from it for the
    reason line); which_fn/run_fn are injectable for tests."""
    environ = os.environ if environ is None else environ
    which_fn = shutil.which if which_fn is None else which_fn
    run_fn = _default_run if run_fn is None else run_fn
    binary = which_fn("herdr")
    if not binary:
        return {"active": False, "host": None, "version": None,
                "reason": "herdr not found on PATH"}
    rc, out, err = run_fn([binary, "--version"], CLI_TIMEOUT)
    if rc != 0:
        tail = (err or out).strip()[-200:]
        return {"active": False, "host": None, "version": None,
                "reason": "herdr --version failed"
                + (f": {tail}" if tail else "")}
    version = parse_version(out)
    if version is None:
        return {"active": False, "host": None, "version": None,
                "reason": "herdr --version printed no version: "
                + (out.strip()[:120] or "(empty)")}
    if version < MIN_HERDR_VERSION:
        return {"active": False, "host": None,
                "version": version,
                "reason": f"herdr {version_str(version)} is "
                f"below the adapter minimum "
                f"{version_str(MIN_HERDR_VERSION)}"}
    host = HerdrHost(binary, version, run_fn=run_fn)
    rc, out, err = run_fn([binary, "api", "schema", "--json"],
                          CLI_TIMEOUT)
    if rc != 0:
        tail = (err or out).strip()[-200:]
        return {"active": False, "host": None,
                "version": version,
                "reason": "herdr api schema --json failed"
                + (f": {tail}" if tail else "")}
    names = schema_names(out)
    missing = [n for n in REQUIRED_METHODS + REQUIRED_EVENTS
               if n not in names]
    if missing:
        return {"active": False, "host": None,
                "version": version,
                "reason": "herdr schema mismatch: missing "
                + ", ".join(missing)}
    try:
        host.snapshot()
    except HerdrError as exc:
        where = ("HERDR_SOCKET_PATH is set"
                 if environ.get("HERDR_SOCKET_PATH")
                 else "no HERDR_SOCKET_PATH set")
        return {"active": False, "host": None,
                "version": version,
                "reason": f"no reachable herdr session "
                f"({where}): {exc}"}
    return {"active": True, "host": host, "version": version,
            "reason": None}


def inert_line(plan):
    """The ONE line the run record carries when hosting was
    configured but the adapter stayed inert (record_extra key
    `herdr_hosting`, written by the CLI)."""
    return f"inert: {plan['reason']}"
