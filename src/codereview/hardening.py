#!/usr/bin/env python3
"""Process hardening shared by the gate's entry points.

make_non_dumpable(): on Linux, prctl(PR_SET_DUMPABLE, 0)
marks this process non-dumpable, after which /proc/<pid>/
environ (and the rest of /proc/<pid>) is no longer readable
by same-uid child processes. The evidence sandbox's env-only
mode scrubs the CHILD's environment, but a sandboxed command
could read the gate's full environment back out of
/proc/$PPID/environ (Phase 3, P3-04); namespace mode blocked
that incidentally, env-only mode did not. Applied at the CLI
and MCP entry points and lazily at the sandbox and discovery
choke points, so any host process that runs untrusted
commands gets the protection. Failure-silent (hardening is
best-effort, never a run failure), Linux-only, idempotent.
Elsewhere (macOS, Windows) there is no equivalent call: it
returns False and the gate's own environment is not
protected — see THREAT-MODEL.md residual 7.
"""

from __future__ import annotations

import sys

_APPLIED = False


def make_non_dumpable():
    """Mark this process non-dumpable (Linux prctl). Returns
    True when the setting is in effect. Never raises."""
    global _APPLIED
    if _APPLIED:
        return True
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        import ctypes.util
        libname = ctypes.util.find_library("c")
        libc = ctypes.CDLL(libname) if libname \
            else ctypes.CDLL(None)
        PR_SET_DUMPABLE = 4  # <sys/prctl.h>
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
            return False
    except Exception:  # noqa: BLE001 — best-effort by design
        return False
    _APPLIED = True
    return True
