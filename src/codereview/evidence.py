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
  by killing the whole process group, a CPU-time limit, and a
  per-file size limit (POSIX rlimits), all recorded.
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
import time

from .core import _now_iso, redact_secrets

SCHEMA = "codereview.evidence/1"

DEFAULT_TIMEOUT = 600          # seconds, per evidence item
_CPU_SLACK = 5                 # rlimit CPU seconds beyond timeout
_FILE_SIZE_LIMIT = 256 * 1024 * 1024   # RLIMIT_FSIZE per file
_OUTPUT_TAIL_CHARS = 4000      # stored tail, matching _run_tests

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
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
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


def _execute(argv, cwd, timeout, env, allow_network):
    """Run one argv in the sandbox; return (status, exit_code,
    duration_s, output_bytes, network_mode). Never raises for
    child failures — every outcome is data for the record."""
    network_mode = "allowed" if allow_network else "env-only"
    run_argv = list(argv)
    if not allow_network and _unshare_ok():
        run_argv = ["unshare", "-rn"] + run_argv
        network_mode = "namespace"
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
    try:
        out, err = proc.communicate(timeout=timeout)
        status = "passed" if proc.returncode == 0 else "failed"
        return status, proc.returncode, time.monotonic() - started, \
            (out or b"") + (err or b""), network_mode
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except Exception:  # noqa: BLE001
            out, err = b"", b""
        return "timeout", None, time.monotonic() - started, \
            (out or b"") + (err or b""), network_mode


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
        return _record(config, source_dir, items,
                       network_mode=network_mode)
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)


def _record(config, source_dir, items, network_mode):
    default_timeout = _resolve_timeout(
        config.get("timeout"), "'timeout'", DEFAULT_TIMEOUT)
    return {
        "schema": SCHEMA,
        "created_at": _now_iso(),
        "source": str(source_dir),
        "sandbox": {
            "kind": "temp-copy (source tree minus .git, deleted "
                    "after the run)",
            "env": "allow-list only (no provider keys or tokens); "
                   "HOME/TMPDIR inside the sandbox",
            "network": network_mode,
            "limits": {
                "timeout_s_default": default_timeout,
                "cpu_slack_s": _CPU_SLACK,
                "file_size_limit_bytes": _FILE_SIZE_LIMIT,
            },
        },
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
                end = re.search(
                    r"[\s\-–—]+(passed|failed|pass|fail|success|"
                    r"succeeded|ok)\s*[.!]?\s*$", body,
                    re.IGNORECASE)
                if end:
                    outcome = _claimed_outcome(end.group(0))
                    head = body[:end.start()]
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
                  environ=None):
    """Re-run every claimed command in the sandbox and compare.

    Returns {"schema", "claims": [...], "summary": {...}}. Each
    claim's status is "confirmed" (the re-run matches the claim),
    "downgraded" (the re-run contradicts the claim — the claim is
    recorded as not standing), or "error" (the re-run could not
    be performed). The builder's text is data: the claimed command
    string is executed as-is because re-running what was claimed
    is the point — but it executes under the full C5 sandbox
    (temp copy, scrubbed env, no network, limits), never in the
    reviewed tree and never with secrets."""
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
