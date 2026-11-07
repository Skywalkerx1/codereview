"""User feedback — release-gate row L19. Opt-in only.

Nothing in this module runs, or sends anything, unless the user
asks for it:

  codereview report        build the redacted support bundle, show
                           exactly what it holds, and send it only
                           after the user confirms (or passes --yes);
  codereview telemetry     enable | disable | status for the optional
                           anonymous crash ping. OFF by default.

The crash ping carries a fixed, minimal field set (see
`ping_payload`) and never code, diffs, findings, paths, repository
names, policy contents, environment values or hostnames. The
random install id is generated when the user enables the ping and
is deleted when they disable it.

Rules that protect the gate (pinned by tests):
  * sending never changes an exit code, never raises, and uses one
    short attempt;
  * HTTPS only, certificate verification on, no redirects; the one
    exception is plain http to a loopback host, which exists so the
    client can be tested against a local server;
  * the endpoint is the owner's, set in ENDPOINT at release; the
    user can override it with CODEREVIEW_FEEDBACK_URL. While no
    endpoint is configured nothing can be sent, and the report
    command says so and shows the manual route;
  * hooks, probes, evidence commands and agent seats run with a
    scrubbed environment and a relocated HOME, so they find no
    telemetry state and cannot send.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import providers as _providers
from .core import VERSION

PING_SCHEMA = "codereview.crash-ping/1"
ENDPOINT = "https://phpatch.com/codereview/report"  # owner, at release
ISSUES_URL = "https://gitlab.com/superstartelecom/codereview/-/issues"
TIMEOUT_S = 3.0
DAILY_CAP = 5
_MAX_RESPONSE = 65536

PING_FIELDS = ("schema", "version", "git_hash", "python",
               "platform", "machine", "command", "exception_type",
               "top_frame", "exit_code", "install_id")

_OFF = ("0", "false", "off", "no")
_ON = ("1", "true", "on", "yes")


# ------------------------------------------------------------ state

def state_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("CODEREVIEW_STATE_DIR", "").strip()
    if override:
        return override
    xdg = environ.get("XDG_STATE_HOME", "").strip()
    base = xdg or os.path.join(environ.get("HOME", "~"), ".local",
                               "state")
    return os.path.join(base, "codereview")


def _state_path(environ=None):
    return os.path.join(state_dir(environ), "telemetry.json")


def _ratelimit_path(environ=None):
    return os.path.join(state_dir(environ), "ping-limit.json")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def telemetry_mode(environ=None):
    """-> ("off"|"on", why). The environment variable, when set to
    an off value, always wins over any stored consent."""
    environ = os.environ if environ is None else environ
    raw = environ.get("CODEREVIEW_TELEMETRY", "").strip().lower()
    if raw in _OFF:
        return "off", "CODEREVIEW_TELEMETRY is set to off"
    if raw in _ON:
        return "on", "CODEREVIEW_TELEMETRY is set to on"
    state = _read_json(_state_path(environ))
    if state.get("enabled") is True and state.get("install_id"):
        return "on", "enabled with 'codereview telemetry enable'"
    return "off", "not enabled (the default)"


def install_id(environ=None):
    state = _read_json(_state_path(environ))
    value = state.get("install_id")
    return value if isinstance(value, str) and value else None


# --------------------------------------------------------- endpoint

def resolve_endpoint(environ=None):
    """-> (url or None, problem or None)."""
    environ = os.environ if environ is None else environ
    url = environ.get("CODEREVIEW_FEEDBACK_URL", "").strip() \
        or ENDPOINT
    if not url:
        return None, "no feedback endpoint is configured in this build"
    problem = _endpoint_problem(url)
    return (None, problem) if problem else (url, None)


def _is_loopback(host):
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint_problem(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return None
    if parts.scheme == "http" and parts.hostname \
            and _is_loopback(parts.hostname):
        return None
    return ("the feedback endpoint must be https:// "
            "(plain http is accepted only for a loopback host)")


def _post(url, body, content_type, headers=None, timeout=TIMEOUT_S):
    """One POST, no redirects, bounded response. -> (status, text).
    Raises on network failure; callers swallow it."""
    opener = urllib.request.build_opener(_providers._NoRedirect())
    req_headers = {"Content-Type": content_type,
                   "User-Agent": f"codereview/{VERSION}"}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=req_headers,
                                 method="POST")
    try:
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read(_MAX_RESPONSE).decode("utf-8", "replace")
            return resp.status, text
    except urllib.error.HTTPError as exc:
        return exc.code, ""


# ------------------------------------------------------- crash ping

def _top_frame(exc):
    """module:function of the innermost frame inside this package,
    or 'external'. Never a path, a line number or source text."""
    import traceback
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:  # noqa: BLE001
        return "unknown"
    package_dir = os.path.dirname(os.path.abspath(__file__))
    for frame in reversed(frames):
        try:
            if os.path.abspath(frame.filename).startswith(package_dir):
                module = os.path.splitext(
                    os.path.basename(frame.filename))[0]
                return f"codereview.{module}:{frame.name}"
        except Exception:  # noqa: BLE001
            continue
    return "external"


def ping_payload(note, exc, install):
    payload = {
        "schema": PING_SCHEMA,
        "version": note.get("version"),
        "git_hash": note.get("git_hash"),
        "python": note.get("python"),
        "platform": note.get("platform"),
        "machine": note.get("machine"),
        "command": note.get("command"),
        "exception_type": note.get("exception_type"),
        "top_frame": _top_frame(exc),
        "exit_code": 2,
        "install_id": install,
    }
    return {k: payload[k] for k in PING_FIELDS}


def _today():
    return datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y-%m-%d")


def _allow_by_rate_limit(signature, environ=None):
    """At most one ping per signature per day and DAILY_CAP a day.
    Records the attempt. Returns False when limited."""
    path = _ratelimit_path(environ)
    data = _read_json(path)
    today = _today()
    if data.get("day") != today:
        data = {"day": today, "count": 0, "seen": []}
    seen = data.get("seen") if isinstance(data.get("seen"), list) \
        else []
    if signature in seen or int(data.get("count") or 0) >= DAILY_CAP:
        return False
    data["seen"] = seen + [signature]
    data["count"] = int(data.get("count") or 0) + 1
    try:
        _write_json(path, data)
    except OSError:
        return False
    return True


def maybe_send_crash_ping(note, exc, environ=None):
    """Send the minimal ping if (and only if) the user enabled it.
    Never raises; returns True when a request was attempted."""
    try:
        mode, _why = telemetry_mode(environ)
        if mode != "on":
            return False
        url, problem = resolve_endpoint(environ)
        if problem:
            return False
        install = install_id(environ) or str(uuid.uuid4())
        payload = ping_payload(note, exc, install)
        signature = hashlib.sha256(
            f"{payload['exception_type']}|{payload['top_frame']}"
            .encode()).hexdigest()[:16]
        if not _allow_by_rate_limit(signature, environ):
            return False
        _post(url, json.dumps(payload).encode("utf-8"),
              "application/json")
        return True
    except Exception:  # noqa: BLE001 — feedback never breaks a run
        return False


# ------------------------------------------------ telemetry command

def _confirm(prompt, assume_yes, stdin=None):
    if assume_yes:
        return True
    stdin = sys.stdin if stdin is None else stdin
    try:
        interactive = stdin.isatty()
    except Exception:  # noqa: BLE001
        interactive = False
    if not interactive:
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


FIELDS_TEXT = (
    "The crash ping sends only: product version, git hash, Python "
    "version, OS family and architecture, command name, exception "
    "type, the module and function where the crash happened, the "
    "exit code, and a random install id. It never sends code, "
    "diffs, findings, file paths, repository or branch names, "
    "policy contents, environment values, host or user names. "
    "At most one ping per kind of crash per day.")


def telemetry_main(argv, environ=None, stdin=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="codereview telemetry",
        description="Opt-in anonymous crash ping. Off by default.")
    ap.add_argument("action", choices=("enable", "disable", "status"))
    ap.add_argument("--yes", action="store_true",
                    help="confirm without prompting (scripts)")
    args = ap.parse_args(argv)
    environ = os.environ if environ is None else environ
    if args.action == "status":
        mode, why = telemetry_mode(environ)
        url, problem = resolve_endpoint(environ)
        print(f"crash ping: {mode} ({why})")
        print("endpoint: " + (url if url else f"none ({problem})"))
        print(FIELDS_TEXT)
        return 0
    if args.action == "disable":
        removed = False
        for path in (_state_path(environ), _ratelimit_path(environ)):
            try:
                os.unlink(path)
                removed = True
            except OSError:
                pass
        print("crash ping disabled; the install id was deleted."
              if removed else "crash ping was not enabled.")
        return 0
    print(FIELDS_TEXT)
    if not _confirm("Enable the crash ping? [y/N] ", args.yes, stdin):
        print("codereview telemetry: not enabled (confirm at a "
              "prompt, or pass --yes).", file=sys.stderr)
        return 2
    try:
        _write_json(_state_path(environ), {
            "enabled": True, "install_id": str(uuid.uuid4()),
            "enabled_at": _today()})
    except OSError as exc:
        print(f"codereview telemetry: cannot save the setting: "
              f"{exc}", file=sys.stderr)
        return 2
    print("crash ping enabled. Turn it off any time with "
          "'codereview telemetry disable'.")
    return 0


# ----------------------------------------------------- report command

def report_main(argv, environ=None, stdin=None):
    import argparse
    import tempfile
    from . import support
    ap = argparse.ArgumentParser(
        prog="codereview report",
        description="Send a redacted bug report. Nothing is sent "
                    "until you have seen what it holds and "
                    "confirmed.")
    ap.add_argument("--message", default="",
                    help="what went wrong, in your words")
    ap.add_argument("--records", default=None,
                    help="directory holding the run records "
                         "(default: ./codereview-out, then .)")
    ap.add_argument("--no-records", action="store_true",
                    help="leave run records out of the report")
    ap.add_argument("--yes", action="store_true",
                    help="send without prompting (scripts)")
    ap.add_argument("--show", action="store_true",
                    help="print the full contents that would be sent")
    args = ap.parse_args(argv)
    environ = os.environ if environ is None else environ
    with tempfile.TemporaryDirectory(prefix="codereview-report-") \
            as tmp:
        path = os.path.join(tmp, "report.zip")
        try:
            manifest = support.build_bundle(
                path, records_dir=args.records,
                include_records=not args.no_records,
                message=args.message, environ=environ)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview report: could not build the report: "
                  f"{exc}", file=sys.stderr)
            return 2
        print(support.describe(manifest, show=args.show, path=path))
        print(support.WARNING)
        url, problem = resolve_endpoint(environ)
        if url is None:
            print(f"codereview report: nothing was sent — {problem}.",
                  file=sys.stderr)
            _print_manual_route()
            return 2
        if not _confirm(f"Send this report to {url}? [y/N] ",
                        args.yes, stdin):
            print("codereview report: nothing was sent (confirm at "
                  "a prompt, or pass --yes).", file=sys.stderr)
            return 2
        try:
            with open(path, "rb") as fh:
                body = fh.read()
            status, text = _post(url, body, "application/zip",
                                 {"X-CodeReview-Version": VERSION},
                                 timeout=15.0)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview report: sending failed ({type(exc).__name__})"
                  f"; nothing was received.", file=sys.stderr)
            _print_manual_route()
            return 2
        if 200 <= status < 300:
            rid = ""
            try:
                rid = str(json.loads(text).get("id") or "")
            except (ValueError, AttributeError):
                pass
            print("report sent" + (f" (id {rid})." if rid else "."))
            return 0
        print(f"codereview report: the server answered {status}; "
              f"nothing was received.", file=sys.stderr)
        _print_manual_route()
        return 2


def _print_manual_route():
    where = ISSUES_URL or "the project's issue tracker (see README)"
    print(f"You can still report by hand: run 'codereview "
          f"support-bundle', read the file, and attach it at {where}. "
          f"Security problems: see SECURITY.md.", file=sys.stderr)
