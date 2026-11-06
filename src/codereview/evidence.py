#!/usr/bin/env python3
"""Evidence runner — Epic C of the adopted roadmap (Week 2).

The reviewers in a CodeReview panel judge a diff; they cannot run
anything. The evidence runner is the deterministic counterpart:
it executes the project's own configured commands (tests, lint,
SAST) and security adapters (gitleaks, semgrep, dependency audit)
against the change, and stores a content-hashed evidence record
in the run JSON. The gate then treats required evidence as a
first-class input (ticket C3):

  required evidence failed / timed out / errored / missing
      -> the gate is BLOCKED
  required evidence unavailable (the tool is not installed)
      -> the gate is INCONCLUSIVE (a human decides; the tool's
         absence is not the builder's failure)

It also verifies builder claims (ticket C4): commands a builder's
work report claims to have run, with claimed outcomes, are re-run
in the sandbox and compared; a claim whose re-run contradicts it
is downgraded in the record — the claim is never silently trusted
and never silently dropped.

Configuration is a plain dict (loaded from JSON by the CLI). The
shape deliberately mirrors the `[evidence]` table of the Epic B
policy file (B1: "evidence requirements"), so a TOML policy's
evidence section — parsed by `tomllib` into the same nested
dicts — can be handed to `collect()` unchanged when Epic B lands:

    {
      "commands": [
        {"name": "tests", "command": "python -m pytest -q",
         "required": true, "timeout": 900}
      ],
      "adapters": [
        {"name": "gitleaks", "required": true},
        {"name": "semgrep", "required": false,
         "args": ["--config", "p/default"]},
        {"name": "dependency-audit", "required": false}
      ],
      "require": ["gitleaks"],
      "timeout": 600,
      "allow_network": false
    }

Defaults: configured commands are required unless marked
otherwise (a configured test command the operator did not mark
optional is there to gate); adapters are optional unless marked
required. `require` names evidence that policy demands be
present: a required name with no configured item is recorded as
status "missing" and blocks the gate — that is how a policy
requires a tool's presence without configuring how it runs (C2).

Threat model (ticket C5)
------------------------
Evidence commands execute code from the working tree under
review — the same tree whose diff is untrusted data everywhere
else in this product. The runner therefore treats every run as
executing UNTRUSTED code and confines it accordingly:

- Working copy: commands run in a throwaway copy of the tree
  (`.git` excluded), created under the system temp dir and
  deleted afterwards. The reviewed tree is never the cwd, so a
  hostile command cannot rewrite the checkout the operator is
  about to merge, and test side effects die with the copy.
- No secrets: the child environment is built from an allow-list
  (PATH, locale, terminal basics) — provider API keys, tokens,
  SSH agent sockets and every other operator variable stay out.
  HOME and TMPDIR point inside the sandbox, so credential files
  (~/.gitconfig, ~/.netrc, cloud SDK configs) are not reachable
  through them either. NEVER run evidence with the operator's
  environment: that is the one configuration this module refuses
  to offer.
- No network by default: proxy variables are stripped (most
  tooling egresses through them) and, where Linux user+network
  namespaces are available (`unshare -rn`), the command runs in
  a namespace with no network at all. The record states which
  mode actually applied ("namespace" vs "env-only"), never
  claiming isolation that did not happen. An item must opt in
  with "allow_network": true to run unrestricted — adapters
  whose rule sets are fetched (semgrep --config auto) need that
  opt-in, and the opt-in is visible in the record.
- Resource limits: each run has a wall-clock timeout enforced
  by killing the whole process group, a CPU-time limit, a
  per-file size limit (POSIX rlimits), and a cap on captured
  output per stream (the child is drained past the cap, never
  blocked on a full pipe; the record's hash and tail cover the
  capped bytes and a truncation marker says so; if a detached
  process holds a pipe open past the post-kill settle, the
  capture is marked incomplete rather than silently partial),
  all recorded.
  What the sandbox does NOT confine — filesystem reach outside
  the copy, memory growth, and the other residual risks — is
  stated plainly in the full threat model, `THREAT-MODEL.md`
  at the repository root.
- Output is evidence, not truth: the full output is hashed
  (sha256) and only a redacted tail is stored, through the same
  `redact_secrets` the review path uses — a scanner that prints
  the secret it found must not smuggle it into the record.

Trust boundary, stated plainly: the commands and adapter choices
come from the operator (CLI flag / policy file), never from the
diff or the tree under review — the same trust level as
`--test-command`. A repository that ships its own evidence
config has it used only when the operator points the CLI at it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from . import hardening
from .core import _now_iso, redact_secrets

SCHEMA = "codereview.evidence/1"

DEFAULT_TIMEOUT = 600          # seconds, per evidence item
_CPU_SLACK = 5                 # rlimit CPU seconds beyond timeout
_FILE_SIZE_LIMIT = 256 * 1024 * 1024   # RLIMIT_FSIZE per file
_OUTPUT_CAP_BYTES = 8 * 1024 * 1024    # captured output, per stream
_OUTPUT_TAIL_CHARS = 4000      # stored tail, matching _run_tests
_KILL_SETTLE_S = 30            # post-kill drain budget — the
                               # pre-cap runner's second
                               # communicate() used the same 30 s

STATUSES = ("passed", "failed", "timeout", "unavailable",
            "missing", "error")

# The only operator environment an evidence child inherits by
# default — the evidence analogue of providers._AGENT_ENV_BASE.
# Proxy variables are NOT in the base list: they are added back
# only for an item that explicitly allows network.
_ENV_BASE = (
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER",
    "LOGNAME", "SHELL", "SYSTEMROOT", "WINDIR", "PATHEXT",
    "COMSPEC",
)
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "no_proxy")


# ------------------------------------------------------------------ config

def load_config(path):
    """Load an evidence config (JSON) from `path` -> dict.

    Raises ValueError with a plain message on any problem; the
    CLI turns that into exit 2 (usage error), the same handling
    as a bad fixture manifest."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            config = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not read evidence config: {exc}")
    if not isinstance(config, dict):
        raise ValueError("evidence config must be a JSON object")
    validate_config(config)
    return config


def validate_config(config):
    """Shape-check a config dict. The same dict shape a TOML
    `[evidence]` table produces: lists of tables for `commands`
    and `adapters`, a list of names for `require`."""
    for key in ("commands", "adapters"):
        items = config.get(key) or []
        if not isinstance(items, list):
            raise ValueError(f"evidence config: {key!r} must be a list")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"evidence config: each {key} entry must be an object")
    for item in config.get("commands") or []:
        if not str(item.get("command") or "").strip():
            raise ValueError(
                "evidence config: a command entry has no 'command'")
    for item in config.get("adapters") or []:
        name = str(item.get("name") or "").strip()
        if name not in ADAPTERS:
            raise ValueError(
                f"evidence config: unknown adapter {name!r} "
                f"(known: {', '.join(sorted(ADAPTERS))})")
    req = config.get("require") or []
    if not isinstance(req, list):
        raise ValueError("evidence config: 'require' must be a list")
    _checked_timeout(config.get("timeout"), "'timeout'")
    for key in ("commands", "adapters"):
        for item in config.get(key) or []:
            _checked_timeout(item.get("timeout"),
                             f"a {key} entry's 'timeout'")


def _checked_timeout(raw, label):
    """Resolve an optional timeout field: absent (None) returns
    None and the caller applies its default; a present value
    must be a positive number. An explicit 0 — like any
    non-positive or non-numeric value — is refused loudly HERE,
    at load, never silently swapped for a default via a falsey
    `or` (9489ee49db6f; the review-v13 contract that
    providers.command_agent documents)."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            f"evidence config: {label} must be a number of "
            f"seconds, got {raw!r}")
    if raw <= 0:
        raise ValueError(
            f"evidence config: {label} must be positive, got "
            f"{raw!r} — a non-positive timeout is refused, not "
            "silently replaced by the default")
    return raw


def _resolve_timeout(raw, label, default):
    checked = _checked_timeout(raw, label)
    return default if checked is None else checked


# ------------------------------------------------------------------ sandbox

def _copy_tree(source, dest):
    """Copy the working tree (minus .git) into the sandbox.
    Symlinks are copied as links, never dereferenced, so a link
    planted in the tree cannot pull outside content into the copy
    (the command may still follow it at run time — inside a
    throwaway cwd, with a scrubbed environment)."""
    def _ignore(_dir, names):
        return [n for n in names if n == ".git"]
    shutil.copytree(source, dest, ignore=_ignore, symlinks=True)


def _sandbox_env(sandbox, allow_network, environ=None):
    """Build the child environment from the allow-list. `environ`
    is injectable for tests; the operator's real environment is
    the default SOURCE of allow-listed names only — nothing else
    crosses."""
    environ = os.environ if environ is None else environ
    env = {n: environ[n] for n in _ENV_BASE if n in environ}
    if allow_network:
        env.update({n: environ[n] for n in _PROXY_VARS
                    if n in environ})
    home = os.path.join(sandbox, "home")
    tmp = os.path.join(sandbox, "tmp")
    os.makedirs(home, exist_ok=True)
    os.makedirs(tmp, exist_ok=True)
    env["HOME"] = home
    env["TMPDIR"] = tmp
    env["CODEREVIEW_EVIDENCE"] = "1"
    return env


_UNSHARE_OK = None


def _unshare_ok():
    """Probe once per process whether `unshare -rn` (user +
    network namespace) actually works here; cached. A sandbox or
    kernel that forbids user namespaces yields False and the
    runner falls back to env-only network restriction — and says
    so in the record."""
    global _UNSHARE_OK
    if _UNSHARE_OK is None:
        if sys.platform.startswith("linux") and \
                shutil.which("unshare"):
            try:
                out = subprocess.run(
                    ["unshare", "-rn", "true"],
                    capture_output=True, timeout=10, check=False)
                _UNSHARE_OK = out.returncode == 0
            except Exception:  # noqa: BLE001
                _UNSHARE_OK = False
        else:
            _UNSHARE_OK = False
    return _UNSHARE_OK


def _kill_group(proc):
    """Kill the child's whole process group (it runs in its own
    session), so a timed-out command leaves no grandchildren
    behind — the same discipline as the agent seats."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, OSError):
        # The child has exited and been reaped (the normal-exit
        # path, P3-06): its pid is gone, but it WAS its group
        # leader (start_new_session), so the pid IS the pgid —
        # and the group can still hold live grandchildren.
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _apply_limits(timeout):
    """preexec_fn: POSIX rlimits for the evidence child. A limit
    that cannot be set must not kill the child before it starts;
    the wall-clock timeout (enforced by the parent) always
    applies regardless."""
    def _set(res, value):
        try:
            resource.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass
    _set(resource.RLIMIT_CPU, int(timeout) + _CPU_SLACK)
    _set(resource.RLIMIT_FSIZE, _FILE_SIZE_LIMIT)


def _drain(stream, sink):
    """Reader-thread body: pull `stream` to EOF, keeping at
    most _OUTPUT_CAP_BYTES in sink["data"] and draining (and
    discarding) the rest, so a spewing child never blocks on a
    full pipe and never grows the parent's memory without
    bound. sink["truncated"] records that output was dropped."""
    try:
        while True:
            # read1, not read: read(n) waits until n bytes or
            # EOF, which would strand a trickling child's
            # available bytes inside the buffer when EOF never
            # comes (a detached pipe holder); read1 returns
            # whatever one raw read delivers.
            chunk = stream.read1(65536)
            if not chunk:
                break
            room = _OUTPUT_CAP_BYTES - len(sink["data"])
            if room > 0:
                sink["data"] += chunk[:room]
            if len(chunk) > max(room, 0):
                sink["truncated"] = True
    except Exception:  # noqa: BLE001 — a dead stream is EOF
        pass
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass


def _captured(out_sink, err_sink, incomplete=False):
    """The combined output bytes the record hashes and tails:
    stdout then stderr, exactly as the pre-cap runner combined
    them, plus markers (visible in the tail, and covered by
    the hash) for the two ways the bytes can be less than what
    the child wrote: a truncation marker when either stream
    hit the cap, and — when a drainer was still blocked after
    the post-kill settle because a detached process holds the
    pipe open — an incomplete-capture marker. Partial output
    is never presented as whole."""
    output = bytes(out_sink["data"]) + bytes(err_sink["data"])
    if out_sink["truncated"] or err_sink["truncated"]:
        output += (
            f"\n[codereview: output truncated at the sandbox "
            f"cap of {_OUTPUT_CAP_BYTES} bytes per stream]\n"
        ).encode("utf-8")
    if incomplete:
        output += (
            "\n[codereview: output capture incomplete — a "
            "detached process still holds the pipe]\n"
        ).encode("utf-8")
    return output


# ------------------------------------------------- env-only exposure note

# P3-04 follow-up: env-only mode has no pid namespace, so a
# sandboxed child running as the operator's uid can read
# /proc/<pid>/environ of ANY dumpable same-uid process. The
# gate's own process is hardened (hardening.make_non_
# dumpable), but sibling processes — the operator's shell,
# IDE, other agents — are not ours to harden, and namespace
# mode is the only mode that closes the channel. When a run
# actually executes env-only while the gate process's own
# environment carries key-shaped variable NAMES, the run
# says so: once on stderr, and in the evidence record.
_KEY_SHAPED_NAME_RE = re.compile(r"API_KEY|SECRET|TOKEN|PASSWORD")
_ENV_ONLY_WARNING_EMITTED = False


def _key_shaped_env_names(environ=None):
    """Names (never values) of key-shaped variables in the
    gate process's own environment — the names a sandboxed
    child could go hunting for in a sibling process."""
    env = os.environ if environ is None else environ
    return sorted(
        name for name in env
        if _KEY_SHAPED_NAME_RE.search(name)
        or name.endswith("_KEY"))


def _env_only_key_warning(names):
    return (
        "sandbox ran in env-only mode (no namespace): a "
        "sandboxed command running as this user can read the "
        "environment of any dumpable same-user process via "
        "/proc/<pid>/environ; key-shaped environment "
        "variables are present ("
        + ", ".join(names) +
        "), so the 'provider keys never reach an evidence "
        "process' property does not hold in this mode — "
        "see THREAT-MODEL.md residual 7.")


def _note_env_only_exposure(network_mode):
    """Return the env-only exposure warning text when this
    execution ran env-only with key-shaped names in the gate
    environment, else None. The first such execution in the
    process also prints the warning to stderr (once per
    run, not per command)."""
    global _ENV_ONLY_WARNING_EMITTED
    if network_mode != "env-only":
        return None
    names = _key_shaped_env_names()
    if not names:
        return None
    text = _env_only_key_warning(names)
    if not _ENV_ONLY_WARNING_EMITTED:
        _ENV_ONLY_WARNING_EMITTED = True
        print(f"codereview: warning: {text}", file=sys.stderr)
    return text


def _execute(argv, cwd, timeout, env, allow_network,
             settle_s=_KILL_SETTLE_S):
    """Run one argv in the sandbox; return (status, exit_code,
    duration_s, output_bytes, network_mode). Never raises for
    child failures — every outcome is data for the record.

    Output is read by drainer threads under a per-stream cap
    (see _drain); the wait semantics mirror the communicate()
    contract this replaces: the run ends when the child has
    exited AND both pipes reach EOF, bounded by the timeout —
    a grandchild that inherits a pipe and holds it open past
    the deadline is a timeout, exactly as before."""
    # P3-04 backstop: the child below is a direct child of
    # this process in env-only mode and could read the gate's
    # environment from /proc/$PPID/environ; the CLI/MCP entry
    # points harden at start, this lazy call covers library
    # hosts that never went through them.
    hardening.make_non_dumpable()
    network_mode = "allowed" if allow_network else "env-only"
    run_argv = list(argv)
    if not allow_network and _unshare_ok():
        run_argv = ["unshare", "-rn"] + run_argv
        network_mode = "namespace"
    if network_mode == "env-only":
        # Surface the sibling-/proc residual (THREAT-MODEL
        # residual 7) when it is live for this run.
        _note_env_only_exposure(network_mode)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            run_argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            preexec_fn=lambda: _apply_limits(timeout))
    except Exception as exc:  # noqa: BLE001
        return "error", None, 0.0, \
            f"could not start: {exc}".encode("utf-8", "replace"), \
            network_mode
    out_sink = {"data": bytearray(), "truncated": False}
    err_sink = {"data": bytearray(), "truncated": False}
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout,
                                              out_sink),
                         daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr,
                                              err_sink),
                         daemon=True),
    ]
    for reader in readers:
        reader.start()
    return _supervise_sandbox_run(
        proc, readers, timeout, started, out_sink, err_sink,
        network_mode, settle_s=settle_s)


def _supervise_sandbox_run(proc, readers, timeout, started,
                           out_sink, err_sink, network_mode,
                           settle_s=_KILL_SETTLE_S):
    """The evidence sandbox's supervised wait — the pairing
    the v14 subprocess-timeout guard accepts by name for
    _execute's Popen, as it does providers' seat wait: every
    wait here is deadline-bounded (wait(timeout=...), bounded
    joins) and expiry kills the whole process group. It is a
    stronger bound than communicate(timeout=...), not a
    weaker one: communicate buffers the child's output
    without bound, this wait drains it under the C5 cap."""
    def _settle(deadline):
        """True when the child has exited and both pipes are
        drained by `deadline` (an absolute monotonic time)."""
        for reader in readers:
            reader.join(max(deadline - time.monotonic(), 0.0))
        return proc.poll() is not None and not any(
            reader.is_alive() for reader in readers)

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    if not timed_out and not _settle(started + timeout + 2.0):
        # The child exited but a pipe is still not drained
        # shortly after the deadline — a grandchild inherited
        # it and is holding it open. communicate() reported
        # this as a timeout; so does the sandbox. (The 2 s
        # grace covers the final pipe bytes of a child that
        # exited right at its deadline.)
        timed_out = True
    if timed_out:
        _kill_group(proc)
        try:
            proc.wait(timeout=settle_s)
        except Exception:  # noqa: BLE001
            pass
        # Post-kill drain: after the group kill the pipes
        # reach EOF and the drainers finish, so the sinks are
        # final before _captured reads them. A drainer still
        # blocked after the settle means a detached process
        # (outside the killed group) holds the pipe — the
        # capture is then partial, and _captured marks it
        # incomplete rather than presenting it as whole.
        final = _settle(time.monotonic() + settle_s)
        return "timeout", None, time.monotonic() - started, \
            _captured(out_sink, err_sink, incomplete=not final), \
            network_mode
    status = "passed" if proc.returncode == 0 else "failed"
    # P3-06: the timeout path kills the process group; the
    # normal path must too — a backgrounded child with
    # redirected stdio (sleep 60 >/dev/null &) otherwise
    # survives a passed run and outlives the sandbox.
    # _kill_group tolerates an already-dead group.
    _kill_group(proc)
    return status, proc.returncode, time.monotonic() - started, \
        _captured(out_sink, err_sink), network_mode


def _result(name, kind, required, status, exit_code, duration,
            output, detail="", command=None, network_mode=None):
    return {
        "name": name, "kind": kind, "required": bool(required),
        "status": status, "exit_code": exit_code,
        "duration_s": round(duration, 3),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_tail": redact_secrets(
            output.decode("utf-8", errors="replace")
        )[-_OUTPUT_TAIL_CHARS:] if output else "",
        "detail": detail,
        "command": command,
        "network_mode": network_mode,
    }


# ------------------------------------------------------------------ adapters (C2)

def _adapter_gitleaks(workdir, item, path_env):
    tool = shutil.which("gitleaks", path=path_env)
    if not tool:
        return None, "gitleaks not found on PATH"
    argv = [tool, "detect", "--source", ".", "--no-git",
            "--redact"] + [str(a) for a in item.get("args") or []]
    return argv, ""


def _adapter_semgrep(workdir, item, path_env):
    tool = shutil.which("semgrep", path=path_env)
    if not tool:
        return None, "semgrep not found on PATH"
    # --config auto fetches rules: the item needs
    # "allow_network": true to fetch them under the sandbox; a
    # local rule path passed via args runs fully offline.
    argv = [tool, "scan", "--config", "auto", "--error",
            "--quiet"] + [str(a) for a in item.get("args") or []]
    return argv, ""


def _adapter_dependency_audit(workdir, item, path_env):
    """First available dependency-audit tool wins; a tree with no
    supported ecosystem and no scanner is `unavailable`, never a
    crash. Extra args from the config are appended."""
    args = [str(a) for a in item.get("args") or []]
    tool = shutil.which("osv-scanner", path=path_env)
    if tool:
        return [tool, "-r", "."] + args, ""
    tool = shutil.which("pip-audit", path=path_env)
    if tool:
        return [tool] + args, ""
    if os.path.exists(os.path.join(workdir, "package.json")):
        tool = shutil.which("npm", path=path_env)
        if tool:
            return [tool, "audit", "--json"] + args, ""
    return None, ("no dependency-audit tool available "
                  "(looked for: osv-scanner, pip-audit, npm "
                  "with a package.json)")


ADAPTERS = {
    "gitleaks": _adapter_gitleaks,
    "semgrep": _adapter_semgrep,
    "dependency-audit": _adapter_dependency_audit,
}


# ------------------------------------------------------------------ collect (C1)

def collect(config, source_dir, environ=None):
    """Run the configured evidence against a sandboxed copy of
    `source_dir` and return the evidence record dict (stored in
    the run JSON under "evidence"). Never raises for tool or
    command failures — every outcome is recorded; a failure to
    even build the sandbox is recorded as an `error` item so a
    required-evidence gate still sees it."""
    validate_config(config)
    config = config or {}
    default_timeout = _resolve_timeout(
        config.get("timeout"), "'timeout'", DEFAULT_TIMEOUT)
    default_network = bool(config.get("allow_network"))
    items = []

    sandbox_root = tempfile.mkdtemp(prefix="codereview-evidence-")
    workdir = os.path.join(sandbox_root, "tree")
    try:
        try:
            _copy_tree(source_dir, workdir)
        except Exception as exc:  # noqa: BLE001
            for entry in config.get("commands") or []:
                items.append(_result(
                    str(entry.get("name") or entry.get("command")),
                    "command", entry.get("required", True), "error",
                    None, 0.0, b"",
                    detail=f"sandbox copy failed: {exc}",
                    command=str(entry.get("command"))))
            for entry in config.get("adapters") or []:
                items.append(_result(
                    str(entry.get("name")), "adapter",
                    entry.get("required", False), "error", None, 0.0,
                    b"", detail=f"sandbox copy failed: {exc}"))
            return _record(config, source_dir, items,
                           network_mode="not-run")

        for entry in config.get("commands") or []:
            command = str(entry.get("command"))
            name = str(entry.get("name") or command)
            timeout = _resolve_timeout(
                entry.get("timeout"),
                f"command {name!r} 'timeout'", default_timeout)
            allow_network = bool(entry.get("allow_network",
                                           default_network))
            env = _sandbox_env(sandbox_root, allow_network,
                               environ=environ)
            status, code, duration, output, net = _execute(
                ["sh", "-c", command], workdir, timeout, env,
                allow_network)
            items.append(_result(
                name, "command", entry.get("required", True),
                status, code, duration, output,
                command=command, network_mode=net))

        for entry in config.get("adapters") or []:
            name = str(entry.get("name"))
            timeout = _resolve_timeout(
                entry.get("timeout"),
                f"adapter {name!r} 'timeout'", default_timeout)
            allow_network = bool(entry.get("allow_network",
                                           default_network))
            argv, why = ADAPTERS[name](
                workdir, entry,
                (environ or os.environ).get("PATH", ""))
            if argv is None:
                items.append(_result(
                    name, "adapter", entry.get("required", False),
                    "unavailable", None, 0.0, b"", detail=why))
                continue
            env = _sandbox_env(sandbox_root, allow_network,
                               environ=environ)
            status, code, duration, output, net = _execute(
                argv, workdir, timeout, env, allow_network)
            items.append(_result(
                name, "adapter", entry.get("required", False),
                status, code, duration, output,
                command=" ".join(argv[1:]) if len(argv) > 1
                        else argv[0],
                network_mode=net))

        present = {it["name"] for it in items}
        for name in config.get("require") or []:
            if str(name) not in present:
                items.append(_result(
                    str(name), "required", True, "missing", None,
                    0.0, b"",
                    detail="required by policy but not configured "
                           "or run"))
        modes = {it.get("network_mode") for it in items
                 if it.get("network_mode")}
        network_mode = (modes.pop() if len(modes) == 1
                        else "mixed" if modes else "not-run")
        sandbox_warning = None
        if any(it.get("network_mode") == "env-only"
               for it in items):
            names = _key_shaped_env_names()
            if names:
                sandbox_warning = _env_only_key_warning(names)
        return _record(config, source_dir, items,
                       network_mode=network_mode,
                       sandbox_warning=sandbox_warning)
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)


def _record(config, source_dir, items, network_mode,
            sandbox_warning=None):
    default_timeout = _resolve_timeout(
        config.get("timeout"), "'timeout'", DEFAULT_TIMEOUT)
    sandbox = {
        "kind": "temp-copy (source tree minus .git, deleted "
                "after the run)",
        "env": "allow-list only (no provider keys or tokens); "
               "HOME/TMPDIR inside the sandbox",
        "network": network_mode,
        "limits": {
            "timeout_s_default": default_timeout,
            "cpu_slack_s": _CPU_SLACK,
            "file_size_limit_bytes": _FILE_SIZE_LIMIT,
            "output_cap_bytes_per_stream": _OUTPUT_CAP_BYTES,
        },
    }
    if sandbox_warning:
        # Present only when the exposure it names was live
        # for this run (env-only mode + key-shaped names in
        # the gate environment); absent otherwise, so a
        # record without it is the unexposed shape.
        sandbox["warning"] = sandbox_warning
    return {
        "schema": SCHEMA,
        "created_at": _now_iso(),
        "source": str(source_dir),
        "sandbox": sandbox,
        "items": items,
    }


# ------------------------------------------------------------------ gate (C3)

def gate_effect(items):
    """The C3 gate rule as a pure function over evidence items.

    Returns (effect, reasons): effect is "blocked",
    "inconclusive", or None (evidence does not move the gate).
    Required items that failed, timed out, errored, or are
    missing block; required items that are merely unavailable
    (tool not installed) make the run inconclusive — the
    distinction between "the change failed its evidence" and
    "this machine could not produce the evidence"."""
    blocked, inconclusive = [], []
    for item in items or []:
        if not item.get("required"):
            continue
        status = item.get("status")
        name = item.get("name")
        if status in ("failed", "timeout", "error", "missing"):
            detail = item.get("detail") or status
            blocked.append(
                f"required evidence {name!r} {status} ({detail})"
                if status in ("error", "missing") else
                f"required evidence {name!r} {status}")
        elif status == "unavailable":
            inconclusive.append(
                f"required evidence {name!r} unavailable "
                f"({item.get('detail') or 'tool not installed'})")
    if blocked:
        return "blocked", blocked + inconclusive
    if inconclusive:
        return "inconclusive", inconclusive
    return None, []


# ------------------------------------------------------------------ builder claims (C4)

# A claim is a command the builder's report asserts was run, with
# a claimed outcome. Two documented forms:
#   A. a backtick-quoted command with an outcome on the same line:
#        Ran `python -m pytest -q` — passed
#   B. a labelled line:  "Tests: python -m pytest -q (exit 0)"
# Anything else — a command with no stated outcome, prose about
# testing in general — is not a verifiable claim and is ignored,
# never guessed at.
_CLAIM_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:ran|command|cmd|tests?|check)\s*:\s*(.+)$",
    re.IGNORECASE)
_SPAN_RE = re.compile(r"`([^`\n]{1,300})`")
_EXIT_RE = re.compile(r"exit(?:\s+code)?\s*(\d+)", re.IGNORECASE)
# Word-boundary matching throughout: "ok" must not match inside
# "broken", and an outcome word inside the command itself (e.g.
# `grep error log`) must not fabricate a claim — for labelled
# lines the outcome is only read from the tail after the last
# separator, or from a trailing outcome word.
_FAIL_WORD_RE = re.compile(r"\b(failed|fail|failure|error)\b",
                           re.IGNORECASE)
_PASS_WORD_RE = re.compile(
    r"\b(passed|pass|success|succeeded|ok)\b", re.IGNORECASE)
_TAIL_SEPS = (" — ", " – ", " | ", " (")
# P2-06: outcome words with counts are read count-first — a
# bare word search reads "12 passed, 0 failed" as FAILED
# because "failed" appears at all, and cannot see "0 errors"
# as the pass claim it is.
_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|failures?|errors?)\b", re.IGNORECASE)
# A negated failure ("did not fail", "no failures", "never
# failed", "not failed") is a pass claim, never a failure.
_NEGATED_FAIL_RE = re.compile(
    r"\b(?:did not|never|not|no)\s+"
    r"(?:fail|failed|failure|failures|error|errors)\b",
    re.IGNORECASE)
# P2-07: the trailing outcome word of a labelled line is found
# with this end-anchored search; the separator run before it
# is walked by hand (see parse_claims). The old single regex
# (separator-run + word) backtracked quadratically on long
# separator runs.
_TRAILING_OUTCOME_RE = re.compile(
    r"(passed|failed|pass|fail|success|succeeded|ok)"
    r"\s*[.!]?\s*$", re.IGNORECASE)
_TRAILING_SEP_CHARS = " \t-–—"


def _claimed_outcome(text):
    """-> ("passed"|"failed", exit_code|None) or None."""
    match = _EXIT_RE.search(text)
    if match:
        code = int(match.group(1))
        return ("passed" if code == 0 else "failed"), code
    if "✗" in text or "✘" in text:
        return "failed", None
    if "✅" in text or "✓" in text:
        return "passed", None
    counts = {}
    for num, word in _COUNT_RE.findall(text):
        counts[word.lower()] = counts.get(word.lower(), 0) + int(num)
    if counts:
        bad = sum(counts.get(w, 0) for w in
                  ("failed", "failure", "failures",
                   "error", "errors"))
        if bad > 0:
            return "failed", None
        if counts.get("passed", 0) > 0 or any(
                w in counts for w in
                ("failed", "failure", "failures",
                 "error", "errors")):
            # Reached only with bad == 0: some tests passed, or
            # a failure/error count is explicitly zero.
            return "passed", None
    if _NEGATED_FAIL_RE.search(text):
        return "passed", None
    if _FAIL_WORD_RE.search(text):
        return "failed", None
    if _PASS_WORD_RE.search(text):
        return "passed", None
    return None


def parse_claims(report_text):
    """Extract verifiable claims from a builder work report.
    Returns [{command, claimed, claimed_exit_code, line}] with
    the report's line numbers (1-based)."""
    claims = []
    for lineno, line in enumerate(
            (report_text or "").splitlines(), start=1):
        span = _SPAN_RE.search(line)
        label = _CLAIM_LABEL_RE.match(line)
        if span:
            command = span.group(1).strip()
            # The outcome is read from the line with the command
            # span REMOVED, so words inside the command (an
            # `error` argument, a file named ok.txt) never count.
            rest = line[:span.start()] + line[span.end():]
            outcome = _claimed_outcome(rest)
            if command and outcome:
                claims.append({
                    "command": command,
                    "claimed": outcome[0],
                    "claimed_exit_code": outcome[1],
                    "line": lineno})
            continue
        if label:
            body = label.group(1).strip().strip("`")
            head, tail = body, ""
            for sep in _TAIL_SEPS:
                if sep in body:
                    head, tail = body.rsplit(sep, 1)
                    tail = sep + tail
            outcome = _claimed_outcome(tail) if tail else None
            if outcome is None and not tail:
                # P2-07: end-anchored word search + a hand
                # walk over the separator run — linear, where
                # the old separator-run regex backtracked
                # quadratically on long runs.
                end = _TRAILING_OUTCOME_RE.search(body)
                if end:
                    start = end.start()
                    while start > 0 and body[start - 1] in \
                            _TRAILING_SEP_CHARS:
                        start -= 1
                    if start < end.start():
                        outcome = _claimed_outcome(
                            body[start:end.end()])
                        head = body[:start]
            if outcome:
                command = _EXIT_RE.sub("", head)
                command = " ".join(command.split()).strip()
                command = command.rstrip("—–- ").strip()
                if command:
                    claims.append({
                        "command": command,
                        "claimed": outcome[0],
                        "claimed_exit_code": outcome[1],
                        "line": lineno})
    return claims


def verify_claims(report_text, source_dir, timeout=DEFAULT_TIMEOUT,
                  environ=None, claims=None):
    """Re-run every claimed command in the sandbox and compare.

    Returns {"schema", "claims": [...], "summary": {...}}. Each
    claim's status is "confirmed" (the re-run matches the claim),
    "downgraded" (the re-run contradicts the claim — the claim is
    recorded as not standing), or "error" (the re-run could not
    be performed). The builder's text is data: the claimed command
    string is executed as-is because re-running what was claimed
    is the point — but it executes under the full C5 sandbox
    (temp copy, scrubbed env, no network, limits), never in the
    reviewed tree and never with secrets.

    `claims` may carry a pre-parsed claim list (the output of
    parse_claims on the same text) so a caller that already
    parsed the report does not pay for — or diverge on — a
    second parse (P2-07); None parses `report_text` here."""
    if claims is None:
        claims = parse_claims(report_text)
    results = []
    sandbox_root = tempfile.mkdtemp(prefix="codereview-claims-")
    workdir = os.path.join(sandbox_root, "tree")
    try:
        try:
            _copy_tree(source_dir, workdir)
            copy_error = ""
        except Exception as exc:  # noqa: BLE001
            copy_error = f"sandbox copy failed: {exc}"
        for claim in claims:
            entry = dict(claim)
            if copy_error:
                entry.update(status="error", actual_exit_code=None,
                             detail=copy_error)
                results.append(entry)
                continue
            env = _sandbox_env(sandbox_root, False, environ=environ)
            status, code, duration, output, net = _execute(
                ["sh", "-c", claim["command"]], workdir, timeout,
                env, False)
            if claim["claimed_exit_code"] is not None:
                confirmed = code == claim["claimed_exit_code"]
            elif claim["claimed"] == "passed":
                confirmed = code == 0
            else:
                confirmed = code not in (0, None)
            entry.update(
                status="confirmed" if confirmed else "downgraded",
                actual_exit_code=code,
                duration_s=round(duration, 3),
                output_sha256=hashlib.sha256(output).hexdigest(),
                detail="" if confirmed else
                f"claimed {claim['claimed']}"
                + (f" (exit {claim['claimed_exit_code']})"
                   if claim["claimed_exit_code"] is not None
                   else "")
                + f"; re-run exited {code} ({status})")
            results.append(entry)
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)
    summary = {
        "total": len(results),
        "confirmed": sum(1 for r in results
                         if r["status"] == "confirmed"),
        "downgraded": sum(1 for r in results
                          if r["status"] == "downgraded"),
        "error": sum(1 for r in results if r["status"] == "error"),
    }
    return {"schema": SCHEMA, "claims": results, "summary": summary}
