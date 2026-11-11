"""Crash handling — release-gate row L17.

An unexpected error must never reach the user as a raw traceback,
and must never be mistaken for a verdict. `run_guarded` wraps the
command-line entry point:

  * any uncaught exception prints ONE line to stderr, writes a
    redacted crash note next to the records, and exits 2 — the
    same code as "inconclusive", so CI can never read a crash as
    a PASS (0) or a plain block (1);
  * `--debug` or CODEREVIEW_DEBUG=1 additionally prints the
    redacted traceback;
  * KeyboardInterrupt exits 130 with one line; a closed pipe
    exits quietly (141);
  * everything about reporting is best-effort: nothing in this
    module can raise out of `run_guarded`, change a gate
    outcome, or delay the exit beyond the short ping timeout.

The crash note is a local file. It is redacted with the same
`redact_secrets` the records use, and it never contains the
environment. Sending anything anywhere is feedback.py's job, is
opt-in, and is attempted only after the note is on disk.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import sys
import traceback
from collections.abc import Callable

from .core import VERSION, redact_secrets

SCHEMA = "codereview.crash/1"
EXIT_CRASH = 2
EXIT_INTERRUPT = 130
EXIT_BROKEN_PIPE = 141

DOCS_POINTER = ("This is a bug; run 'codereview support-bundle' "
                "and see SECURITY.md / CONTRIBUTING.md.")

_SECRET_FLAG_WORDS = ("key", "token", "secret", "password", "passwd",
                      "credential", "auth")
_MAX_MESSAGE = 500
_MAX_TRACEBACK = 20000

# Callables the entry points register to run after a crash (for
# example: mark a GitHub commit status pending). Best-effort.
_crash_hooks: list[Callable[..., object]] = []


def register_crash_hook(fn):
    _crash_hooks.append(fn)


def clear_crash_hooks():
    del _crash_hooks[:]


def build_identity():
    """Version, and the git hash when the build stamped one
    (src/codereview/_build_info.py with GIT_HASH, or the
    CODEREVIEW_GIT_HASH variable)."""
    git_hash = os.environ.get("CODEREVIEW_GIT_HASH", "").strip() \
        or None
    if git_hash is None:
        try:
            from . import _build_info  # type: ignore
            git_hash = getattr(_build_info, "GIT_HASH", None)
        except Exception:  # noqa: BLE001 — optional module
            git_hash = None
    return {"version": VERSION, "git_hash": git_hash}


def redact_argv(argv):
    """Redact a command line: secret-shaped text in any argument,
    and the value after (or inside) a flag whose name looks like
    it carries a credential."""
    out = []
    hide_next = False
    for arg in argv or []:
        arg = str(arg)
        if hide_next:
            out.append("[REDACTED]")
            hide_next = False
            continue
        if arg.startswith("-"):
            name, eq, _value = arg.partition("=")
            if any(w in name.lower() for w in _SECRET_FLAG_WORDS):
                if eq:
                    out.append(name + "=[REDACTED]")
                else:
                    out.append(arg)
                    hide_next = True
                continue
        out.append(redact_secrets(arg))
    return out


def _command_name(argv):
    for arg in argv or []:
        if not str(arg).startswith("-"):
            return str(arg)[:40]
        break
    return "review"


def _safe_text(text, limit):
    try:
        return redact_secrets(str(text))[:limit]
    except Exception:  # noqa: BLE001
        return "[unavailable]"


def build_crash_note(exc, argv):
    tb_text = "".join(traceback.format_exception(
        type(exc), exc, exc.__traceback__))
    note = {
        "schema": SCHEMA,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **build_identity(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "command": _command_name(argv),
        "argv": redact_argv(argv),
        "exception_type": type(exc).__name__,
        "message": _safe_text(exc, _MAX_MESSAGE),
        "traceback": _safe_text(tb_text, _MAX_TRACEBACK),
    }
    return note


def _crash_dir(argv):
    override = os.environ.get("CODEREVIEW_CRASH_DIR", "").strip()
    if override:
        return override
    args = [str(a) for a in argv or []]
    for i, arg in enumerate(args):
        if arg == "--out" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--out="):
            return arg[len("--out="):]
    return "."


def write_crash_note(note, argv):
    """Write the note; return its path, or None when no directory
    could be written (never raises)."""
    stamp = note["created_at"].replace("-", "").replace(":", "")
    name = f"codereview-crash-{stamp}-{os.getpid()}.json"
    for directory in (_crash_dir(argv), "."):
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, name)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(note, fh, indent=2, sort_keys=True)
                fh.write("\n")
            return path
        except OSError:
            continue
    return None


def _say(text):
    try:
        print(text, file=sys.stderr)
    except Exception:  # noqa: BLE001 — stderr itself may be gone
        pass


def _split_debug(argv):
    """-> (argv without --debug, debug_requested)."""
    debug = os.environ.get("CODEREVIEW_DEBUG", "").strip() == "1"
    clean = []
    for arg in argv:
        if arg == "--debug":
            debug = True
        else:
            clean.append(arg)
    return clean, debug


def _handle_crash(exc, argv, debug):
    try:
        note = build_crash_note(exc, argv)
        path = write_crash_note(note, argv)
    except Exception:  # noqa: BLE001 — the handler must not crash
        note, path = None, None
    kind = type(exc).__name__
    message = _safe_text(exc, 200).replace("\n", " ")
    line = f"codereview: internal error ({kind}): {message}. " \
           f"{DOCS_POINTER}"
    if path:
        line += f" Crash note: {path}"
    _say(line)
    if debug and note is not None:
        _say(note["traceback"].rstrip())
    for hook in list(_crash_hooks):
        try:
            hook()
        except Exception:  # noqa: BLE001 — best effort only
            pass
    if note is not None:
        try:
            from . import feedback
            feedback.maybe_send_crash_ping(note, exc)
        except Exception:  # noqa: BLE001 — never affects the exit
            pass


def run_guarded(fn, argv=None):
    """Run `fn(argv)` (the CLI main) under the crash policy and
    return the process exit code."""
    raw = list(sys.argv[1:] if argv is None else argv)
    clean, debug = _split_debug(raw)
    try:
        rc = fn(clean)
        return 0 if rc is None else rc
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        _say(str(code))
        return 1
    except KeyboardInterrupt:
        _say("codereview: interrupted.")
        return EXIT_INTERRUPT
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:  # noqa: BLE001
            pass
        return EXIT_BROKEN_PIPE
    except Exception as exc:  # noqa: BLE001 — the point of this module
        _handle_crash(exc, clean, debug)
        return EXIT_CRASH
    finally:
        clear_crash_hooks()
