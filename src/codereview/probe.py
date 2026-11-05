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
import subprocess
import sys
import tempfile
import time

PROBE_TIMEOUT_DEFAULT = 120
_OUTPUT_CAP = 20000
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
            shutil.copytree(tree_dir, work, ignore=_IGNORE)
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
        try:
            res = subprocess.run(
                prefix + argv, cwd=work, env=_sandbox_env(tmp, work),
                capture_output=True, text=True,
                timeout=timeout)
            output = (res.stdout or "") + (res.stderr or "")
            outcome = "pass" if res.returncode == 0 else "fail"
            exit_code = res.returncode
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or b"") if isinstance(
                exc.stdout, bytes) else (exc.stdout or "")) \
                + ((exc.stderr or b"") if isinstance(
                    exc.stderr, bytes) else (exc.stderr or ""))
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
            outcome, exit_code = "timeout", None
        except Exception as exc:  # noqa: BLE001 — an outcome, not a crash
            output = f"probe spawn failed: {exc}"
            outcome, exit_code = "error", None
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
                        "timeout_s": timeout},
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
                           f"{res['sandbox'].get('network')}")}
    return probe_fn
