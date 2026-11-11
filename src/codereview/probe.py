"""Probe harness (refutation-process solution §5.2,
owner-adopted 2026-11-04): the harness — never a model —
executes probes in a sandbox, and a Tech Lead (binding or
shadow) may request exactly ONE probe round per case
(MAX_PROBE_ROUNDS in core). The Tech Lead never executes
anything itself; it emits a machine-executable probe SPEC,
this module runs it, and the structured result goes back
into the adjudication as evidence.

Sandbox discipline:
- The reviewed tree is COPIED to a fresh temp directory and
  the probe runs there; the real tree is never the cwd, so a
  probe cannot mutate the code under review.
- The environment is an ALLOWLIST (PATH, LANG, LC_*, TERM,
  plus a temp HOME/TMPDIR): provider keys, tokens and every
  other process secret are absent by construction, not by
  filtering.
- Network: when the platform offers `unshare -n`, the probe
  runs inside a network namespace with no interfaces; the
  level actually achieved is recorded on the result —
  never overstated.
- A hard wall-clock timeout bounds every probe.
- Resource limits and tree kill (the C5 discipline the
  evidence sandbox established): the probe runs in its own
  session under POSIX rlimits (CPU time, address space,
  per-file size, open files; core dumps off — the
  address-space cap is not enforced by macOS, and there the
  result's sandbox.memory_cap says so), its output
  is drained under a per-stream byte cap so a spewing
  probe cannot grow the harness's memory, and expiry —
  or normal exit — kills the probe's whole process
  group, so children a probe forks cannot outlive it.

Probe semantics: a probe tests the CLAIM's falsifiable
prediction. Exit 0 means the probe's assertion held. The
result carries `can_rebut: True, can_support: False` — the
adopted asymmetry: probe evidence may rebut a finding (it
feeds the refutation side's evidence); it can never sustain
a finding by itself, and a sustain decision must still
carry its own validated quote from the code region.
"""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

try:
    import resource
except ImportError:  # non-POSIX: no rlimits to apply
    resource = None

PROBE_TIMEOUT_DEFAULT = 120
_OUTPUT_CAP = 20000
# C5 sandbox discipline (the evidence sandbox's conventions,
# src/codereview/evidence.py): the wall-clock timeout is the
# primary bound; these are the backstops that hold even if
# supervision itself misbehaves.
_CPU_SLACK_S = 5            # RLIMIT_CPU = timeout + this
_PROBE_MEMORY_LIMIT = 2 * 1024 * 1024 * 1024    # RLIMIT_AS:
                            # ~100x a bare interpreter's
                            # footprint, so fat stacks fit,
                            # while resident growth (RSS can
                            # never exceed AS) stays bounded
_PROBE_FILE_SIZE_LIMIT = 256 * 1024 * 1024      # RLIMIT_FSIZE
                            # per file (evidence convention)
_PROBE_OPEN_FILES_LIMIT = 1024                  # RLIMIT_NOFILE
_PROBE_OUTPUT_CAP_BYTES = 8 * 1024 * 1024       # captured per
                            # stream, drained past the cap
                            # (evidence convention)
_KILL_SETTLE_S = 10         # post-kill drain budget
_DRAIN_GRACE_S = 2          # post-exit pipe-drain grace
# RLIMIT_NPROC is deliberately NOT set: it is a per-USER
# ceiling, not a per-tree one — the probe shares the
# operator's uid, whose live process count could already
# exceed any sane per-probe budget and would then break
# every fork a legitimate probe makes. Process-count
# containment comes from the process-group kill plus the
# CPU/address-space limits above.
_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM")
_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "codereview-out",
    "bench-out", "acceptance-out")

_unshare_level = None


def _network_prefix():
    """argv prefix isolating the network namespace, or
    ([], 'env-only') when the platform cannot. Probed once
    per process; the achieved level is recorded, honestly."""
    global _unshare_level
    if _unshare_level is None:
        _unshare_level = ([], "env-only")
        exe = shutil.which("unshare")
        if exe:
            try:
                res = subprocess.run(
                    [exe, "-n", "true"], capture_output=True,
                    timeout=10)
                if res.returncode == 0:
                    _unshare_level = ([exe, "-n"],
                                      "network-namespace")
            except Exception:  # noqa: BLE001 — level stays env-only
                pass
    return _unshare_level


def parse_probe_spec(request):
    """Normalize a probe request into an executable spec, or
    None when the request carries nothing machine-executable.

    Accepted shapes (dict, JSON text, or prose with one
    embedded JSON object):
      {"kind": "python",  "code": "<script>", "claim": "..."}
      {"kind": "command", "argv": ["prog", "arg", ...]}
      {"kind": "test",    "target": "tests/test_x.py"}
    """
    spec = None
    if isinstance(request, dict):
        spec = request
    elif isinstance(request, str) and request.strip():
        text = request.strip()
        try:
            parsed = json.loads(text)
            spec = parsed if isinstance(parsed, dict) else None
        except ValueError:
            spec = None
        if spec is None:
            start = text.find("{")
            while start != -1:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                parsed = json.loads(text[start:i + 1])
                            except ValueError:
                                parsed = None
                            if isinstance(parsed, dict) \
                                    and parsed.get("kind"):
                                spec = parsed
                            break
                if spec is not None:
                    break
                start = text.find("{", start + 1)
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("kind") or "").strip().lower()
    out = {"kind": kind, "claim": str(spec.get("claim") or "")}
    if kind == "python":
        code = spec.get("code")
        if not isinstance(code, str) or not code.strip():
            return None
        out["code"] = code
        return out
    if kind == "command":
        argv = spec.get("argv")
        if not isinstance(argv, list) or not argv \
                or not all(isinstance(a, str) and a
                           for a in argv):
            return None
        out["argv"] = list(argv)
        return out
    if kind == "test":
        target = spec.get("target")
        if not isinstance(target, str) or not target.strip():
            return None
        out["target"] = target
        return out
    return None


def _sandbox_env(tmp, work):
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["HOME"] = tmp
    env["TMPDIR"] = tmp
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The copied tree root is importable, so a python probe
    # can import the reviewed code exactly as the tree lays
    # it out (the probe script itself lives in a subdir,
    # whose directory would otherwise shadow sys.path).
    env["PYTHONPATH"] = work
    return env


def _memory_cap_enforced():
    """Whether the RLIMIT_AS cap actually bounds a probe's
    memory on this platform. macOS accepts or ignores the
    request but never enforces it (getrlimit inside the probe
    still reports unlimited and a 10 GiB reservation
    succeeds), and RLIMIT_DATA there does not bound mmap'd
    heaps either, so on macOS the probe's memory is uncapped
    and its result says so rather than claiming the cap."""
    return resource is not None and sys.platform != "darwin"


def _memory_cap_note():
    if _memory_cap_enforced():
        return f"RLIMIT_AS {_PROBE_MEMORY_LIMIT} bytes"
    return ("not enforced on this platform: the probe's "
            "memory is uncapped (bounded only by the "
            "wall-clock and CPU limits)")


def _apply_probe_limits(timeout):
    """preexec_fn body (executed in the child): POSIX
    rlimits for the probe. A limit that cannot be set must
    not kill the child before it starts; the wall-clock
    timeout (enforced by the parent) always applies
    regardless."""
    if resource is None:
        return

    def _set(res, value):
        try:
            resource.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass

    _set(resource.RLIMIT_CPU, int(timeout) + _CPU_SLACK_S)
    _set(resource.RLIMIT_AS, _PROBE_MEMORY_LIMIT)
    _set(resource.RLIMIT_FSIZE, _PROBE_FILE_SIZE_LIMIT)
    _set(resource.RLIMIT_NOFILE, _PROBE_OPEN_FILES_LIMIT)
    _set(resource.RLIMIT_CORE, 0)


def _kill_probe_group(proc):
    """Kill the probe's whole process group (it runs in its
    own session), so a timed-out — or merely backgrounding —
    probe leaves no children behind. Never raises."""
    killpg = getattr(os, "killpg", None)
    if killpg is not None:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError, OSError):
            # The child has exited and been reaped (the
            # normal-exit path): it WAS its group leader
            # (start_new_session), so the pid IS the pgid —
            # and the group can still hold live
            # grandchildren.
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


def _drain_probe_stream(stream, sink):
    """Reader-thread body: pull `stream` to EOF, keeping at
    most _PROBE_OUTPUT_CAP_BYTES in sink["data"] and
    draining (and discarding) the rest, so a spewing probe
    never blocks on a full pipe and never grows the
    harness's memory without bound. sink["truncated"]
    records that output was dropped."""
    try:
        while True:
            # read1, not read: read(n) waits until n bytes or
            # EOF, which would strand a trickling probe's
            # available bytes inside the buffer when EOF
            # never comes (a detached pipe holder).
            chunk = stream.read1(65536)
            if not chunk:
                break
            room = _PROBE_OUTPUT_CAP_BYTES - len(sink["data"])
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


def _probe_settled(proc, readers, deadline):
    """True when the probe has exited and both pipes are
    drained by `deadline` (an absolute monotonic time)."""
    for reader in readers:
        reader.join(max(deadline - time.monotonic(), 0.0))
    return proc.poll() is not None and not any(
        reader.is_alive() for reader in readers)


def _probe_output(out_sink, err_sink, incomplete=False):
    """The combined output text the result records: stdout
    then stderr, exactly as the harness has always combined
    them, plus a marker when the bytes are less than what
    the probe wrote — partial output is never presented as
    whole."""
    output = bytes(out_sink["data"]).decode("utf-8", "replace") \
        + bytes(err_sink["data"]).decode("utf-8", "replace")
    if out_sink["truncated"] or err_sink["truncated"]:
        output += (
            f"\n[codereview] probe output truncated at the "
            f"sandbox cap of {_PROBE_OUTPUT_CAP_BYTES} bytes "
            f"per stream")
    if incomplete:
        output += (
            "\n[codereview] probe output capture incomplete — "
            "a detached process still holds the pipe")
    return output


def _execute_probe(argv, cwd, env, timeout):
    """Run one probe command under the C5 discipline and
    return (outcome, exit_code, output) in run_probe's
    long-standing vocabulary: pass (exit 0), fail (any
    other exit — a signal death included, its exit_code
    the negative signal number, exactly as subprocess has
    always reported it), timeout (the wall clock expired,
    or a forked child holding a pipe forced the deadline),
    error (the harness itself could not run the probe).
    Never raises for probe failures — they are outcomes."""
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=lambda: _apply_probe_limits(timeout))
    except Exception as exc:  # noqa: BLE001 — an outcome, not a crash
        return "error", None, f"probe spawn failed: {exc}"
    out_sink = {"data": bytearray(), "truncated": False}
    err_sink = {"data": bytearray(), "truncated": False}
    readers = [
        threading.Thread(target=_drain_probe_stream,
                         args=(proc.stdout, out_sink),
                         daemon=True),
        threading.Thread(target=_drain_probe_stream,
                         args=(proc.stderr, err_sink),
                         daemon=True),
    ]
    for reader in readers:
        reader.start()
    return _supervise_probe_execution(
        proc, readers, out_sink, err_sink, timeout,
        time.monotonic())


def _supervise_probe_execution(proc, readers, out_sink,
                               err_sink, timeout, started):
    """The probe's supervised wait — the pairing the
    subprocess-timeout guard accepts by name, as it does
    the evidence sandbox's: every wait here is
    deadline-bounded (wait(timeout=...), bounded joins)
    and expiry kills the whole process group. It is a
    stronger bound than communicate(timeout=...), not a
    weaker one: communicate buffers the child's output
    without bound, this wait drains it under the C5 cap."""
    try:
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        if not timed_out and not _probe_settled(
                proc, readers,
                started + timeout + _DRAIN_GRACE_S):
            # The probe exited but a pipe is still not
            # drained at the deadline — a child it forked
            # inherited the pipe and is holding it open.
            # subprocess.run reported this as a timeout (and
            # could hang on it after the kill); so does the
            # sandbox.
            timed_out = True
        if timed_out:
            _kill_probe_group(proc)
            try:
                proc.wait(timeout=_KILL_SETTLE_S)
            except Exception:  # noqa: BLE001
                pass
            # Post-kill drain: after the group kill the
            # pipes reach EOF and the drainers finish, so
            # the sinks are final before the output is read.
            # A drainer still blocked after the settle means
            # a detached process (outside the killed group)
            # holds the pipe — the capture is partial and
            # is marked incomplete, never presented whole.
            final = _probe_settled(
                proc, readers,
                time.monotonic() + _KILL_SETTLE_S)
            return "timeout", None, _probe_output(
                out_sink, err_sink, incomplete=not final)
        # Normal exit: kill the group anyway — a probe that
        # backgrounded a child with redirected stdio and
        # then exited cleanly must not leave that child
        # running past the sandbox (the evidence runner's
        # P3-06 lesson). _probe_settled above has already
        # confirmed the readers are done, so the captured
        # output is final.
        _kill_probe_group(proc)
        outcome = "pass" if proc.returncode == 0 else "fail"
        return outcome, proc.returncode, _probe_output(
            out_sink, err_sink)
    except Exception as exc:  # noqa: BLE001 — an outcome, not a crash
        _kill_probe_group(proc)
        return "error", None, f"probe execution failed: {exc}"


def run_probe(spec, tree_dir, timeout=PROBE_TIMEOUT_DEFAULT):
    """Execute one probe spec against a temp COPY of
    `tree_dir`. Returns the structured result:
    {outcome: pass|fail|error|timeout, exit_code, duration_s,
     output, output_sha256, sandbox, spec,
     can_rebut: True, can_support: False}.
    Never raises for probe failures — they are outcomes."""
    spec = parse_probe_spec(spec)
    if spec is None:
        return {"outcome": "error", "exit_code": None,
                "duration_s": 0.0, "output": "",
                "output_sha256": hashlib.sha256(b"").hexdigest(),
                "sandbox": {}, "spec": None,
                "can_rebut": True, "can_support": False,
                "detail": "probe request carried no "
                          "machine-executable spec"}
    tmp = tempfile.mkdtemp(prefix="codereview-probe-")
    started = time.monotonic()
    try:
        work = os.path.join(tmp, "tree")
        if tree_dir and os.path.isdir(tree_dir):
            try:
                # symlinks=True, as in evidence._copy_tree: a
                # link planted in the reviewed tree must arrive
                # as a link, never be dereferenced into the
                # copy — dereferencing would pull the target's
                # content (any host file the operator can read)
                # into the sandbox tree, and would stream a
                # special file (e.g. /dev/zero) into the copy
                # in THIS process, unbounded (L6 F1/F2).
                shutil.copytree(tree_dir, work, ignore=_IGNORE,
                                symlinks=True)
            except Exception as exc:  # noqa: BLE001 — an outcome
                # A copy failure is a probe outcome, never an
                # exception escaping run_probe (its contract:
                # probe failures are outcomes, not crashes).
                return {"outcome": "error", "exit_code": None,
                        "duration_s": round(
                            time.monotonic() - started, 3),
                        "output": "",
                        "output_sha256": hashlib.sha256(
                            b"").hexdigest(),
                        "sandbox": {}, "spec": spec,
                        "can_rebut": True, "can_support": False,
                        "detail": f"probe tree copy failed: {exc}"}
        else:
            os.makedirs(work)
        if spec["kind"] == "python":
            probe_dir = os.path.join(work, ".codereview-probe")
            os.makedirs(probe_dir, exist_ok=True)
            script = os.path.join(probe_dir, "probe_main.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(spec["code"])
            argv = [sys.executable, script]
        elif spec["kind"] == "command":
            argv = list(spec["argv"])
        else:  # test — execute through the unittest runner
            # (discovery rooted at the target's directory), NOT
            # as a plain script: script execution runs zero
            # tests when the file lacks a __main__ guard and
            # still exits 0 (finding 4cf81c69d7cf).
            target = spec["target"]
            start = os.path.dirname(target) or "."
            argv = [sys.executable, "-m", "unittest",
                    "discover", "-s", start,
                    "-p", os.path.basename(target)]
        prefix, net_level = _network_prefix()
        outcome, exit_code, output = _execute_probe(
            prefix + argv, work, _sandbox_env(tmp, work),
            timeout)
        if spec["kind"] == "test" and outcome in ("pass",
                                                   "fail"):
            # A test probe's verdict is evidence only if tests
            # actually executed. A runner invocation that ran
            # zero tests (an empty module, a target discovery
            # matched nothing in) must be recorded as an error,
            # never as a verdict — whether the interpreter
            # exits 0 for it or 5 (4cf81c69d7cf).
            ran = re.findall(r"Ran (\d+) tests?", output)
            if (ran and int(ran[-1]) == 0) or (
                    not ran and outcome == "pass"):
                outcome = "error"
                output += ("\n[codereview] test probe executed "
                           "zero tests — refusing to report "
                           "a verdict")
        duration = time.monotonic() - started
        return {
            "outcome": outcome, "exit_code": exit_code,
            "duration_s": round(duration, 3),
            "output": output[:_OUTPUT_CAP],
            "output_sha256": hashlib.sha256(
                output.encode("utf-8")).hexdigest(),
            "sandbox": {"cwd": "temp-copy",
                        "network": net_level,
                        "env": "allowlist",
                        "timeout_s": timeout,
                        "memory_cap": _memory_cap_note()},
            "spec": spec,
            "can_rebut": True, "can_support": False,
            "detail": (f"harness probe {outcome} "
                       f"(exit {exit_code}, {duration:.1f}s)"),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_probe_fn(tree_dir, timeout=PROBE_TIMEOUT_DEFAULT):
    """The probe_fn contract run_review consumes —
    probe_fn(finding, request) -> {"outcome",
    "evidence_quote", "detail", ...}. A request with no
    executable spec is `inconclusive`, NOT an escalation for
    lack of a channel: the channel exists; the request was
    not executable."""
    def probe_fn(finding, request):
        spec = parse_probe_spec(request)
        if spec is None:
            return {"outcome": "inconclusive",
                    "evidence_quote": "",
                    "detail": "probe channel wired, but the "
                              "request carried no "
                              "machine-executable spec (want "
                              "JSON: {\"kind\": \"python\", "
                              "\"code\": ...} / {\"kind\": "
                              "\"command\", \"argv\": [...]} / "
                              "{\"kind\": \"test\", \"target\": "
                              "...})",
                    "can_rebut": True, "can_support": False}
        res = run_probe(spec, tree_dir, timeout=timeout)
        quote = ""
        for line in (res.get("output") or "").splitlines():
            if line.strip():
                quote = line.strip()[:300]
                break
        return {**res, "evidence_quote": quote,
                "detail": (f"{res['detail']}; output sha256 "
                           f"{res['output_sha256'][:12]}…; "
                           f"sandbox network="
                           f"{res['sandbox'].get('network')}"
                           + ("" if _memory_cap_enforced()
                              else "; memory cap not enforced "
                                   "on this platform"))}
    return probe_fn
