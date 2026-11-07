#!/usr/bin/env python3
"""codereview attention notifications (Epic L4).

A long gate run should call the operator back instead of
waiting to be checked. When a seat enters a blocked state
(the Epic K2 classes — quota, auth, input, stalled) or the
gate reaches a verdict, the run fires ONE local command the
operator configured: a terminal bell, a desktop toast, a
herdr-style attention hook. No hosted service, no
CodeReview-managed endpoint — the command is the operator's
own, on their own machine.

Configuration surface: the USER SETUP only — a `[notify]`
table in the saved config (see userconfig.py):

    [notify]
    command = ["my-notify-script"]

Notifications are operator preference, not project contract:
the project policy (.codereview.toml) has no notify key and
cannot set one (policy.load_policy rejects the table as
unknown). A run with no [notify] command configured behaves
exactly as before this epic — no invocations, and the record
carries no `notifications` section.

Argv contract: the configured argv is executed directly
(no shell) with two arguments appended — the event name and
a one-line summary:

    <command...> seat_blocked "seat cx blocked:quota"
    <command...> verdict      "gate blocked: 3 finding(s)"

Bounds and recording: each invocation is bounded by
NOTIFY_TIMEOUT_S; the outcome (status ok / failed / timeout
/ error, exit code, duration) is appended to the run
record's `notifications` section. A failing, missing, or
hanging notifier is recorded and never delays the run beyond
the bound, never changes a finding or the verdict, and never
raises into the review. The command runs in its own process
group, and the group is killed when the invocation ends —
on timeout (L10/NT9: a timed-out notifier leaves no
grandchildren behind) and on normal exit (a notifier that
backgrounds a helper and returns leaves nothing running;
a helper that must outlive the notification has to detach
into its own session, the documented setsid boundary).
Duplicate suppression is per run: a seat that ends blocked
in several jobs notifies once per (seat, class); the
verdict notifies once.

Deliberately distinct from Epic L3's lifecycle hooks: L3 is
project-level deterministic automation declared in the
project policy and executed inside the evidence sandbox; L4
is a personal local command declared in the user setup and
executed as the operator, inheriting the operator's
environment — it is a doorbell, not a build step.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

# The per-invocation bound: long enough for a toast/bell
# command to start and finish, short enough that a wedged
# notifier can never hold a gate run hostage. Two events in
# a run (a blocked seat + the verdict) cost at most twice
# this in the pathological all-hanging case.
NOTIFY_TIMEOUT_S = 5.0

EVENT_SEAT_BLOCKED = "seat_blocked"
EVENT_VERDICT = "verdict"


def _kill_notify_group(proc):
    """Kill the notifier's whole process group (it runs in
    its own session), so a timed-out — or merely
    backgrounding — notifier leaves no children behind.
    Mirrors probe._kill_probe_group (the C5 pattern). Never
    raises."""
    killpg = getattr(os, "killpg", None)
    if killpg is not None:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError, OSError):
            # The child has exited and been reaped: it WAS
            # its group leader (start_new_session), so the
            # pid IS the pgid — and the group can still hold
            # live grandchildren.
            pgid = proc.pid
        try:
            killpg(pgid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def _supervise_notify_run(proc, timeout):
    """The notifier's supervised wait — the pairing the
    subprocess-timeout guard accepts by name, as it does the
    probe harness's and the evidence sandbox's: the wait is
    deadline-bounded (wait(timeout=...)) and expiry kills
    the whole process group, not just the direct child
    (L10/NT9). The group is swept on normal exit too, so a
    notifier that backgrounds a helper and returns leaves
    nothing behind (the P3-06 rule). Raises
    subprocess.TimeoutExpired on a hang, exactly as
    subprocess.run(timeout=...) did."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_notify_group(proc)
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 — reaping is
            pass  # best-effort; the kill already landed
        raise
    _kill_notify_group(proc)
    return proc.returncode


def _default_runner(argv, timeout):
    """Run argv directly (no shell), bounded by `timeout`,
    output discarded (the notification is the side effect;
    anything the command prints is the operator's own console
    business, not the record's). Returns the exit code.
    Raises subprocess.TimeoutExpired on a hang, OSError when
    the command cannot be started at all."""
    proc = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        shell=False, start_new_session=True)
    return _supervise_notify_run(proc, timeout)


# The summary length ceiling (P3-12): a notification is a
# doorbell, not a document — past this the summary is cut
# and marked with an ellipsis.
_SUMMARY_CAP_CHARS = 500


def _one_line(text):
    """The summary as it reaches BOTH the notifier argv and
    the recorded outcome: one line, no control bytes, capped.

    Whitespace runs collapse to single spaces (a seat name is
    operator config and could carry a newline). Every other
    control/escape byte (C0, DEL, C1 — ESC and BEL included,
    so ANSI/OSC sequences lose their teeth) is dropped
    (P3-12): a hostile or merely odd seat name must not
    smuggle terminal escapes into a notifier UI that renders
    raw argv, nor a 100KB string into the record."""
    line = " ".join(str(text or "").split())
    line = "".join(
        ch for ch in line
        if not (ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F))
    if len(line) > _SUMMARY_CAP_CHARS:
        line = line[:_SUMMARY_CAP_CHARS - 1] + "…"
    return line


class Notifier:
    """One run's notification channel: a configured command
    plus the outcomes it produced. Constructed by the caller
    (CLI: from the user setup; tests: with a stub runner) and
    handed to core.run_review / run_verification. Every
    method is total — fire() records and returns, never
    raises."""

    def __init__(self, command, timeout=NOTIFY_TIMEOUT_S,
                 runner=None):
        self.command = [str(c) for c in command]
        self.timeout = float(timeout)
        self._runner = runner or _default_runner
        self._fired = set()
        self.outcomes = []

    def fire(self, event, summary, dedupe_key=None):
        """Invoke the command once for `event`, unless an
        event with `dedupe_key` already fired in this run.
        Returns the recorded outcome dict, or None when the
        invocation was suppressed as a duplicate."""
        key = dedupe_key if dedupe_key is not None else (event,)
        if key in self._fired:
            return None
        self._fired.add(key)
        summary = _one_line(summary)
        argv = self.command + [event, summary]
        started = time.monotonic()
        status, exit_code, detail = "ok", None, None
        try:
            exit_code = self._runner(argv, self.timeout)
            if exit_code != 0:
                status = "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        except Exception as exc:  # noqa: BLE001 — a notifier
            # that cannot even start is an outcome, not a crash
            status = "error"
            detail = str(exc)[:200]
        outcome = {"event": event, "summary": summary,
                   "status": status, "exit_code": exit_code,
                   "duration_ms": int(
                       (time.monotonic() - started) * 1000)}
        if detail:
            outcome["detail"] = detail
        self.outcomes.append(outcome)
        return outcome

    def seat_blocked(self, seat, cls):
        """The blocked-seat event (Epic K2 classes): once per
        (seat, class) per run — a seat blocked in three batch
        jobs is one fact for the operator, not three pings."""
        label = f"blocked:{cls}" if cls else "blocked"
        return self.fire(
            EVENT_SEAT_BLOCKED, f"seat {seat} {label}",
            dedupe_key=(EVENT_SEAT_BLOCKED, str(seat),
                        str(cls)))

    def verdict(self, summary):
        """The gate-verdict event: once per run."""
        return self.fire(EVENT_VERDICT, summary,
                         dedupe_key=(EVENT_VERDICT,))


def notifier_for(command, **kwargs):
    """A Notifier for a configured command argv, or None when
    no command is configured — the unset state, in which the
    review path is byte-identical to before this epic."""
    if not command:
        return None
    return Notifier(command, **kwargs)
