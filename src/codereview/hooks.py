#!/usr/bin/env python3
"""Lifecycle hooks — Epic L3 of the adopted roadmap.

A project may declare shell commands in the `[hooks]` table of
its `.codereview.toml` (validated by policy.py in the B1 style)
that fire at three points in a review run's lifecycle:

  pre-run       before any seat call — fired by the CLI once
                every setup step has succeeded and the run is
                committed;
  on-blocked    after the record is written, when the run's
                first seat (in record order) ended in a K2
                blocked class (quota / auth / input / stalled).
                The name means a SEAT blocked, not that the
                gate verdict is BLOCKED (P6-09): a PASS run
                with a blocked seat fires it, a BLOCKED run
                with no blocked seat does not. The [hooks]
                policy key `on_seat_blocked` is accepted as
                an alias for `on_blocked` (policy.py folds
                it into the same slot);
  post-verdict  after the record is written, on every run that
                configures it.

A hook receives the event name and — for the two post-record
events — the run record's path, in the CODEREVIEW_HOOK_EVENT
/ CODEREVIEW_HOOK_RECORD environment variables, and as the
positional parameters $1 / $2 OF THE COMMAND STRING: the
command runs under `sh -c` with those values as its $1 / $2,
so a shell-string command (`hook.sh "$1" "$2"`) forwards them
to the script, while a bare script path receives no arguments
and must read the environment variables (P5-10, pinned by
tests/test_phase5_fixes.py).

Execution is the Epic C evidence sandbox, reused whole: a hook
runs as a single-command `evidence.collect` config, so it gets
the C5 confinement verbatim — a throwaway copy of the tree as
cwd (.git excluded, deleted afterwards), an environment built
from the allow-list (no provider keys, no tokens), no network
by default, a wall-clock timeout enforced by killing the whole
process group, and output stored as sha256 + a redacted tail.
There is deliberately no second executor in this module.

Timing contract for the post-record events: the record is
written first (so the path handed to the hooks exists and the
file already carries the verdict and the pre-run result), the
hooks fire, and then the CLI appends their results to the
record's `hooks` section and rewrites the record once at the
same path. The file a hook reads is therefore the file that
ends up carrying the complete hooks ledger.

Enforcement flows one way only. A hook's result is data for
the record; a hook that fails, times out, or names a missing
command is recorded and the run continues. Nothing in this
module returns a value the gate reads — there is no path by
which a hook can change a verdict, a finding, or any other
gate input, and `fire_hook` never raises.
"""

from __future__ import annotations

import hashlib
import shlex

from . import evidence as _evidence
from .core import redact_secrets

SCHEMA = "codereview.hooks/1"

# Event names, in lifecycle order, mapped to their [hooks]
# policy keys. Mirrors policy._HOOK_COMMAND_KEYS; a test pins
# the two together so they cannot drift.
EVENTS = ("pre-run", "on-blocked", "post-verdict")
_EVENT_KEYS = {"pre-run": "pre_run", "on-blocked": "on_blocked",
               "post-verdict": "post_verdict"}

# A hook with no configured timeout gets the evidence runner's
# own default bound — one timeout discipline for every command
# the sandbox executes (C5).
DEFAULT_TIMEOUT = _evidence.DEFAULT_TIMEOUT


def hooks_from_policy(policy):
    """The hooks config carried by a loaded policy dict, or
    None when the policy configures no hook command (no
    [hooks] table, or a table with only a timeout). The
    returned dict is keyed by policy key (pre_run / on_blocked
    / post_verdict) plus an optional "timeout"."""
    if not isinstance(policy, dict):
        return None
    hooks = policy.get("hooks") or {}
    config = {}
    for event in EVENTS:
        command = hooks.get(_EVENT_KEYS[event])
        if isinstance(command, str) and command.strip():
            config[_EVENT_KEYS[event]] = command
    if not config:
        return None
    if hooks.get("timeout") is not None:
        config["timeout"] = hooks["timeout"]
    return config


def first_blocked_trigger(reviewer_reports):
    """The on-blocked trigger for a finished round: the first
    reviewer report (in record order) whose seat ended in a K2
    blocked class, as {"seat", "lens", "class", "state_source"}
    — or None when no seat blocked.

    Both seat-state slots are read: `seat_state` is the seat
    that finally served (or failed), and `seat_state_primary`
    is the primary seat's own terminal state when a fallback
    served in its place — a primary that blocked on quota is
    the run's first blocked seat even though the fallback's
    report row reads done. `state_source` names which slot
    matched, so the record says exactly what was read."""
    for report in reviewer_reports or []:
        if not isinstance(report, dict):
            continue
        for key in ("seat_state", "seat_state_primary"):
            state = report.get(key)
            if isinstance(state, dict) \
                    and state.get("state") == "blocked":
                return {"seat": report.get("provider"),
                        "lens": report.get("lens"),
                        "class": state.get("class"),
                        "state_source": key}
    return None


def _wrapped_command(command, event, record_path):
    """The shell string the sandbox executes for a hook: the
    event and record path exported as environment variables,
    then the user's command run by a nested shell with the
    same values as positional arguments $1 / $2 ($0 is a fixed
    label). Every interpolated value is shlex-quoted; the user
    command itself is data to the outer shell, quoted whole."""
    record = record_path or ""
    return (
        f"CODEREVIEW_HOOK_EVENT={shlex.quote(event)} "
        f"CODEREVIEW_HOOK_RECORD={shlex.quote(record)} "
        f"sh -c {shlex.quote(command)} codereview-hook "
        f"{shlex.quote(event)} {shlex.quote(record)}")


def fire_hook(command, event, source_dir, record_path=None,
              timeout=None, environ=None):
    """Run one hook command through the evidence sandbox and
    return its ledger entry. Never raises: a hook that cannot
    even start (the sandbox itself failed) is an "error" entry,
    exactly like an evidence item that could not run.

    The entry: {"event", "command", "record_path", "status",
    "exit_code", "duration_s", "output_sha256", "output_tail",
    "network_mode", "detail"} — status/exit/duration/output
    are the evidence item's own fields, so a hook's outcome is
    recorded with the same fidelity as required evidence.

    The stored "command" is redacted (P6-13): a hook command
    is operator text that can embed a credential (a curl
    header, a token argument), and the record is a durable
    artefact that travels. The EXECUTED command is the raw
    string, unchanged — only the ledger copy passes through
    the same redact_secrets the evidence tails get."""
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    entry = {"event": event, "command": redact_secrets(command),
             "record_path": record_path}
    config = {
        "commands": [{
            "name": f"hook:{event}",
            "command": _wrapped_command(command, event,
                                        record_path),
            "required": False,
            "timeout": timeout}],
        "timeout": timeout,
    }
    try:
        record = _evidence.collect(config, source_dir,
                                   environ=environ)
        items = record.get("items") or []
        item = items[0] if items else {}
    except Exception as exc:  # noqa: BLE001 — recorded, not raised
        item = {"status": "error", "exit_code": None,
                "duration_s": 0.0,
                "output_sha256": hashlib.sha256(b"").hexdigest(),
                "output_tail": "", "network_mode": None,
                "detail": f"hook could not run: {exc}"}
    entry.update({
        "status": item.get("status"),
        "exit_code": item.get("exit_code"),
        "duration_s": item.get("duration_s"),
        "output_sha256": item.get("output_sha256"),
        "output_tail": item.get("output_tail") or "",
        "network_mode": item.get("network_mode"),
        "detail": item.get("detail") or "",
    })
    return entry


class HookRunner:
    """One run's hook ledger: fires each configured event at
    most once, in the order the CLI calls them, and accumulates
    the results the record's `hooks` section carries.

    `blocked_trigger` is set by the CLI (from
    first_blocked_trigger) before on-blocked fires; the
    on-blocked result carries it as its "trigger"."""

    def __init__(self, config, source_dir, environ=None):
        self.config = dict(config or {})
        self.source_dir = source_dir
        self.environ = environ
        self.results = []
        self.blocked_trigger = None
        self._fired = set()

    def configured_events(self):
        """The configured event names, in lifecycle order."""
        return [event for event in EVENTS
                if self.config.get(_EVENT_KEYS[event])]

    def configured(self, event):
        return event in self.configured_events()

    def fire(self, event, record_path=None):
        """Fire `event` if it is configured and has not fired
        yet; return its ledger entry, or None when the event
        does not fire (unconfigured, or already fired — each
        event fires exactly once per run)."""
        if event in self._fired or not self.configured(event):
            return None
        self._fired.add(event)
        entry = fire_hook(
            self.config[_EVENT_KEYS[event]], event,
            self.source_dir, record_path=record_path,
            timeout=self.config.get("timeout"),
            environ=self.environ)
        if event == "on-blocked" \
                and self.blocked_trigger is not None:
            entry["trigger"] = dict(self.blocked_trigger)
        self.results.append(entry)
        return entry

    def section(self):
        """The record's `hooks` section, or None when no hook
        is configured (a hookless run's record carries no hooks
        key at all — byte-identical to before Epic L3)."""
        if not self.configured_events():
            return None
        return {
            "schema": SCHEMA,
            # The configured commands are recorded redacted
            # (P6-13, same rule as the results entries): the
            # config itself keeps the raw text for execution.
            "events": [{"event": event,
                        "command": redact_secrets(
                            self.config[_EVENT_KEYS[event]])}
                       for event in self.configured_events()],
            "blocked_trigger": self.blocked_trigger,
            "results": list(self.results),
        }
