#!/usr/bin/env python3
"""codereview CLI.

Examples:
  codereview --repo . --staged --provider gemini --provider openai
  codereview --patch change.diff --provider xai --provider gemini \
      --test-command "python -m pytest -q"
  codereview --patch fix.diff --verify-previous report.json \
      --builder-response response.md --provider gemini --provider nvidia
  codereview loop --repo . --builder-cmd "your-coding-agent" \
      --provider gemini --provider gemini --provider nvidia
  codereview workflow --file workflow.json --repo . --out wf-out
  codereview pr --repo OWNER/REPO --number 123 --provider gemini
  codereview pr --pr https://github.com/OWNER/REPO/pull/123 --post
  codereview intake issue-report.md --provider gemini \
      --provider nvidia --context src/alerts.py
  codereview sarif review-out --out results.sarif
  codereview policy check   # validate .codereview.toml and
                            # print the effective project policy
  codereview evidence --repo . --config evidence.json
  codereview evidence --repo . --claims builder-report.md

Exit codes: 0 = gate PASS (intake: a solution was produced),
1 = gate BLOCKED, 2 = INCONCLUSIVE or usage/infrastructure error
(intake: every solver failed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import inspect

from . import agentsmd
from . import bench as bench_mod
from . import claims as claims_mod
from . import core
from . import disputes as disputes_mod
from . import hardening
from . import herdrhost
from . import hooks as hooks_mod
from . import notify as notify_mod
from . import policy as policy_mod
from . import evidence as evidence_mod
from . import registry
from . import sarif as sarif_mod
from . import setup_wizard, userconfig
from .providers import (ProviderError, build_providers,
                        describe_spec)


def _run_tests(commands, cwd):
    # shell=True is deliberate: test commands are operator-supplied
    # shell strings (the same trust level as a CI config the operator
    # wrote). They are never taken from the diff under review.
    results = []
    for cmd in commands or []:
        try:
            out = subprocess.run(cmd, shell=True, cwd=cwd,
                                 capture_output=True, timeout=1800,
                                 check=False)
            tail = (out.stdout + out.stderr).decode(
                "utf-8", errors="replace")[-4000:]
            results.append({"command": cmd, "ok": out.returncode == 0,
                            "exit_code": out.returncode,
                            "output_tail": tail})
        except subprocess.TimeoutExpired:
            results.append({"command": cmd, "ok": False,
                            "exit_code": None,
                            "output_tail": "timed out"})
    return results


def _load_patch(args):
    if args.patch:
        with open(os.path.expanduser(args.patch), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    repo = args.repo or "."
    if args.files:
        return core.build_pseudo_patch(args.files, root=repo)
    return core.collect_git_patch(repo, range_spec=args.range,
                                  staged=args.staged)


# The shared containment helper lives in core (P3-11: the
# CLI loaders, core's file-context collector and the
# AGENTS.md collector use ONE implementation). This alias
# keeps the historical cli._is_within name working.
_is_within = core._is_within


def _load_fixture_scope(path, repo="."):
    """Load a versioned fixture manifest (clean-gate solution §3):
    returns the fixture_scope dict run_review records and
    record-verify recomputes — manifest path (repo-relative),
    content hash of the exact bytes, policy version, and the
    enumerated fixture paths. The manifest declares which paths
    are intentionally vulnerable test DATA; a review run only
    classifies fixture findings when the operator passes one."""
    repo_abs = os.path.realpath(repo)
    full = os.path.realpath(
        path if os.path.isabs(path)
        else os.path.join(repo_abs, path))
    if not _is_within(full, repo_abs):
        # The recorded manifest path is replayed by record-verify
        # as a repo-relative object name; a manifest outside the
        # repo could neither be recorded honestly nor verified.
        raise ValueError(
            f"fixture manifest {path}: resolves outside the "
            f"repository ({full})")
    with open(full, "rb") as fh:
        raw = fh.read()
    manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest, dict) \
            or manifest.get("schema") != core.FIXTURE_MANIFEST_SCHEMA:
        raise ValueError(
            f"fixture manifest {path}: schema must be "
            f"{core.FIXTURE_MANIFEST_SCHEMA!r}")
    if manifest.get("policy_version") \
            not in core.FIXTURE_POLICY_VERSIONS:
        raise ValueError(
            f"fixture manifest {path}: unsupported policy_version "
            f"{manifest.get('policy_version')!r} (supported: "
            f"{core.FIXTURE_POLICY_VERSIONS})")
    entries = manifest.get("fixtures")
    if not isinstance(entries, list) or not entries or any(
            not isinstance(e, dict)
            or not str(e.get("path") or "").strip()
            for e in entries):
        raise ValueError(
            f"fixture manifest {path}: 'fixtures' must be a "
            f"non-empty list of objects each naming a 'path'")
    patterns = [str(e["path"]) for e in entries]
    # Optional per-path expected finding counts (v0.9.3, §2f):
    # when an entry declares one, findings on that path beyond
    # the count are NOT classified as expected — they stay in
    # the record as product findings and the excess is noted.
    # Absent = no count expectation (the policy-v1 behaviour).
    expected_counts = {}
    for e in entries:
        if "expected_finding_count" in e:
            v = e.get("expected_finding_count")
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(
                    f"fixture manifest {path}: entry "
                    f"{e.get('path')!r} has a bad "
                    f"expected_finding_count {v!r} (want a "
                    f"non-negative integer)")
            expected_counts[str(e["path"])] = v
    return {
        "manifest_path": os.path.relpath(full, repo_abs).replace(
            os.sep, "/"),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "policy_version": manifest.get("policy_version"),
        "patterns": patterns,
        "expected_counts": expected_counts,
    }


def _load_precedents(path, repo="."):
    """Load the content-addressed precedent store (v0.9.3, §2e):
    returns the precedents dict run_review consumes — entries,
    a blob_lookup resolving a cited path's CURRENT git blob id
    at HEAD, a source_lookup resolving its CURRENT text at HEAD
    (for function-level entries, §5d), and the store's
    repo-relative path + content hash for the record
    (record-verify recomputes both, exactly like the fixture
    manifest). The store declares findings already adjudicated;
    classification additionally requires the cited file's blob
    to be unchanged, so a stale store entry is inert, never
    wrong."""
    repo_abs = os.path.realpath(repo)
    full = os.path.realpath(
        path if os.path.isabs(path)
        else os.path.join(repo_abs, path))
    if not _is_within(full, repo_abs):
        raise ValueError(
            f"precedent store {path}: resolves outside the "
            f"repository ({full})")
    with open(full, "rb") as fh:
        raw = fh.read()
    store = json.loads(raw.decode("utf-8"))
    if not isinstance(store, dict) \
            or store.get("schema") != core.PRECEDENTS_SCHEMA:
        raise ValueError(
            f"precedent store {path}: schema must be "
            f"{core.PRECEDENTS_SCHEMA!r}")
    entries = store.get("entries")
    if not isinstance(entries, list) or any(
            not isinstance(e, dict)
            or not str(e.get("finding_id") or "").strip()
            or not str(e.get("path") or "").strip()
            or not (str(e.get("blob") or "").strip()
                    or (str(e.get("function") or "").strip()
                        and str(e.get("function_hash")
                                or "").strip()))
            for e in entries):
        raise ValueError(
            f"precedent store {path}: 'entries' must be a list "
            f"of objects each naming finding_id, path and a "
            f"content address (blob, or function + "
            f"function_hash for a function-level entry, §5d)")

    def blob_lookup(p):
        out = subprocess.run(
            ["git", "-C", repo_abs, "rev-parse", f"HEAD:{p}"],
            capture_output=True, timeout=120, check=False)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", "replace").strip() or None

    def source_lookup(p):
        out = subprocess.run(
            ["git", "-C", repo_abs, "show", f"HEAD:{p}"],
            capture_output=True, timeout=120, check=False)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", "replace")

    return {
        "entries": entries,
        "blob_lookup": blob_lookup,
        "source_lookup": source_lookup,
        "store_path": os.path.relpath(full, repo_abs).replace(
            os.sep, "/"),
        "store_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _stdin_is_tty():
    try:
        return bool(sys.stdin.isatty())
    except Exception:  # noqa: BLE001 — no stdin, closed stdin
        return False


def _probe_writable(path):
    """Prove `path` can be written into, or return the OSError
    that says it cannot (P5-07b): create the directory chain
    and a temp file for real, then remove them. The Phase 5
    check inferred writability from os.access, which lies for
    a root user on /proc and /sys — the full review ran and
    the late write crashed, discarding the result. A real
    create cannot lie: it fails for root exactly as it fails
    for anyone else. The side effect is brief — the temp file
    is unlinked and any directories the probe created are
    removed again (deepest first, best effort)."""
    missing = []
    probe = path
    while not os.path.exists(probe):
        missing.append(probe)
        probe = os.path.dirname(probe)
    try:
        os.makedirs(path, exist_ok=True)
        fd, tmpname = tempfile.mkstemp(
            dir=path, prefix=".codereview-probe-")
        try:
            os.close(fd)
        finally:
            os.unlink(tmpname)
    except OSError as exc:
        return exc
    finally:
        for created in missing:  # deepest first (walk order)
            try:
                os.rmdir(created)
            except OSError:
                pass
    return None


def _out_dir_problem(out):
    """Why the --out directory cannot be written into, or None
    (P5-07). The check runs at argument-validation time so an
    unwritable --out fails BEFORE any provider call, instead
    of after the review has spent them (when the late crash
    also lost the result). Writability is PROVEN by
    _probe_writable, not inferred from os.access (P5-07b);
    os.access is still consulted first so a plainly unwritable
    ancestor is reported without creating anything."""
    if not out:
        return None
    path = os.path.abspath(os.path.expanduser(out))
    probe = path
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    if not os.path.isdir(probe):
        return f"--out {out}: {probe} is not a directory"
    if not os.access(probe, os.W_OK | os.X_OK):
        if probe == path:
            return f"--out {out}: directory is not writable"
        return (f"--out {out}: cannot be created — "
                f"{probe} is not writable")
    exc = _probe_writable(path)
    if exc is not None:
        return (f"--out {out}: cannot be written "
                f"({exc.strerror or exc})")
    return None


def _refuse_unwritable_out(out, prog):
    """Print the P5-07 refusal and return True when --out is
    unusable, so the caller exits 2 before doing any work."""
    problem = _out_dir_problem(out)
    if problem:
        print(f"{prog}: {problem}", file=sys.stderr)
        return True
    return False


class _ReportWriteFailed(Exception):
    """The review completed but writing its report failed
    (P5-07b): _write_report has already printed the verdict
    and preserved the record — the caller just exits 2."""


def _write_report(report, out_dir, prog, stem=None):
    """core.write_report with the P5-07b late-failure net.

    The up-front --out probe cannot see a disk that fills, a
    permission change or a mount that goes read-only DURING
    the review. When the write then raises OSError, the
    completed review must not be discarded with a traceback:
    the verdict is printed to stdout, the record is written
    to a fallback location (the current directory, then the
    temp directory, then — last resort — stdout itself as
    JSON), and _ReportWriteFailed is raised so the caller
    exits 2. Non-OSError failures (e.g. record-schema
    validation) are NOT caught: they are defects, not
    environment failures, and a fallback write would fail
    identically."""
    try:
        return core.write_report(report, out_dir, stem=stem)
    except OSError as exc:
        print(f"{prog}: report write to {out_dir} failed: "
              f"{exc}", file=sys.stderr)
        gate = str(report.get("gate") or "inconclusive").upper()
        reasons = "; ".join(report.get("gate_reasons") or [])
        print(f"{prog}: gate = {gate} ({reasons})")
        saved = None
        for fallback in (os.getcwd(), tempfile.gettempdir()):
            try:
                saved, _mpath = core.write_report(
                    report, fallback, stem=stem)
                break
            except OSError:
                continue
        if saved is not None:
            print(f"{prog}: record saved to fallback: {saved}")
        else:
            print(f"{prog}: no fallback location was writable; "
                  f"the full record follows on stdout",
                  file=sys.stderr)
            print(json.dumps(report, ensure_ascii=False,
                             indent=2, default=str))
        raise _ReportWriteFailed(str(exc)) from exc


def _run_setup_wizard():
    """The first-run wizard (test seam): the CLI wires the live
    seat probe; tests substitute this to script a setup."""
    return setup_wizard.run_wizard(
        probe_fn=lambda providers: core.run_doctor(providers))


def _evidence_main(argv):
    """codereview evidence — the Epic C evidence runner,
    standalone: run a config's commands/adapters against a tree,
    or verify the claimed commands in a builder's work report.
    Exit codes mirror the gate: 0 = evidence stands (claims:
    every claim confirmed), 1 = required evidence failed /
    a claim was downgraded, 2 = inconclusive or usage error."""
    ap = argparse.ArgumentParser(
        prog="codereview evidence",
        description="Run configured evidence (tests, lint, SAST, "
                    "security adapters) in a sandboxed copy of "
                    "the tree, or verify a builder report's "
                    "claimed commands by re-running them.")
    ap.add_argument("--repo", default=".",
                    help="working tree to run evidence against "
                         "(default: .)")
    ap.add_argument("--config",
                    help="evidence config JSON (commands + "
                         "adapters + policy-required names)")
    ap.add_argument("--claims",
                    help="builder work report (markdown/text): "
                         "re-run its claimed commands and compare")
    ap.add_argument("--out", default="codereview-out",
                    help="output directory for the JSON record "
                         "(default: codereview-out)")
    args = ap.parse_args(argv)
    if bool(args.config) == bool(args.claims):
        print("codereview evidence: pass exactly one of --config "
              "or --claims", file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)
    if args.claims:
        try:
            with open(os.path.expanduser(args.claims),
                      encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception as exc:  # noqa: BLE001
            print(f"codereview evidence: could not read the "
                  f"report: {exc}", file=sys.stderr)
            return 2
        result = evidence_mod.verify_claims(text, args.repo)
        path = os.path.join(args.out, "claims.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        for claim in result["claims"]:
            print(f"  {claim['status']:<10} line "
                  f"{claim['line']}: {claim['command']}"
                  + (f" — {claim['detail']}"
                     if claim.get("detail") else ""))
        summary = result["summary"]
        print(f"codereview evidence: {summary['confirmed']} "
              f"confirmed, {summary['downgraded']} downgraded, "
              f"{summary['error']} error(s) of "
              f"{summary['total']} claim(s)")
        print(f"  data:   {path}")
        if summary["error"]:
            return 2
        return 1 if summary["downgraded"] else 0
    try:
        config = evidence_mod.load_config(args.config)
    except ValueError as exc:
        print(f"codereview: {exc}", file=sys.stderr)
        return 2
    try:
        record = evidence_mod.collect(config, args.repo)
    except Exception as exc:  # noqa: BLE001
        # A collect failure (e.g. a mistyped config value that
        # passes validation and blows up inside a subprocess
        # call) is a subcommand error — exit 2 with the reason,
        # never a traceback (934fab88a12e).
        print(f"codereview evidence: collection failed: {exc}",
              file=sys.stderr)
        return 2
    path = os.path.join(args.out, "evidence.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    for item in record["items"]:
        print(f"  {item['status']:<11} {item['name']}"
              + (" (required)" if item["required"] else "")
              + (f" — {item['detail']}" if item.get("detail")
                 else ""))
    effect, reasons = evidence_mod.gate_effect(record["items"])
    print(f"codereview evidence: gate effect = "
          f"{(effect or 'none').upper()}"
          + (f" ({'; '.join(reasons)})" if reasons else ""))
    print(f"  data:   {path}")
    return {"blocked": 1, "inconclusive": 2}.get(effect, 0)


def _setup_main(argv):
    """codereview setup — first-run (or re-run) user setup:
    pick providers, name the key env vars, assign per-role
    models, save them as YOUR defaults. No panel is imposed."""
    ap = argparse.ArgumentParser(
        prog="codereview setup",
        description="First-run setup: choose your providers, "
                    "keys, and per-role models, and save them "
                    "as your defaults (re-runnable to edit).")
    ap.parse_args(argv)
    try:
        result = _run_setup_wizard()
    except KeyboardInterrupt:
        # P5-06: Ctrl-C is a cancellation, not a crash — no
        # traceback. The wizard saves only at the very end, so
        # nothing was written. 130 is the conventional
        # SIGINT exit code.
        print("codereview setup: cancelled — nothing saved.",
              file=sys.stderr)
        return 130
    except EOFError:
        # P5-13: the wizard already printed its abort line
        # ("setup aborted — nothing saved.") at the prompt that
        # hit EOF; re-printing the exception here duplicated
        # the message.
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"codereview setup: {exc}", file=sys.stderr)
        return 2
    return 0 if result else 2


def _loop_main(argv, providers_override=None):
    """codereview loop — drive review -> builder fix -> verify ->
    advance until PASS or the builder-round budget runs out."""
    ap = argparse.ArgumentParser(
        prog="codereview loop",
        description="Loop driver: reviewers review the working-tree "
                    "diff, a builder command (the coding agent) fixes "
                    "the findings and writes a work report, and a "
                    "verification round decides whether the workflow "
                    "advances.")
    ap.add_argument("--repo", default=".",
                    help="git repository path (default: .)")
    ap.add_argument("--range", dest="range",
                    help="git diff range (default: working tree vs "
                         "HEAD)")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--builder-cmd", required=True,
                    help="command that acts as the coding agent. It "
                         "receives $CODEREVIEW_PACKET (JSON: gate + "
                         "open findings), edits the working tree, and "
                         "writes its work report to $CODEREVIEW_RESPONSE")
    ap.add_argument("--max-rounds", type=int, default=3,
                    help="builder rounds before stopping for a human "
                         "(default 3)")
    ap.add_argument("--waive", action="append", default=[],
                    help="finding ID waived by the owner (recorded "
                         "in the result); repeatable")
    ap.add_argument("--provider", action="append", default=[],
                    help="provider preset or custom spec; repeatable")
    ap.add_argument("--context", default="")
    ap.add_argument("--test-command", action="append", default=[])
    ap.add_argument("--out", default="codereview-out")
    ap.add_argument("--allow-major", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    if _refuse_unwritable_out(args.out, "codereview loop"):
        return 2
    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS") or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if not specs:
            print(userconfig.NOT_SET_UP, file=sys.stderr)
            return 2
        try:
            providers = build_providers(specs)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    os.makedirs(args.out, exist_ok=True)
    packet_path = os.path.join(args.out, "builder-packet.json")
    response_path = os.path.join(args.out, "builder-response.md")

    def get_patch():
        if not args.staged and not args.range:
            core.include_untracked(args.repo)
        return core.collect_git_patch(args.repo, range_spec=args.range,
                                      staged=args.staged)

    def invoke_builder(packet):
        with open(packet_path, "w", encoding="utf-8") as fh:
            json.dump(packet, fh, ensure_ascii=False, indent=1)
        env = dict(os.environ, CODEREVIEW_PACKET=packet_path,
                   CODEREVIEW_RESPONSE=response_path,
                   CODEREVIEW_GATE=str(packet.get("gate") or ""),
                   CODEREVIEW_ROUND=str(packet.get("round") or ""))
        # Legacy aliases (pre-v0.5.0 name) for existing builders.
        for _k in [k for k in env if k.startswith("CODEREVIEW_")]:
            env.setdefault("REVIEWLOOP_" + _k[len("CODEREVIEW_"):],
                           env[_k])
        if os.path.exists(response_path):
            os.remove(response_path)
        out = subprocess.run(args.builder_cmd, shell=True, cwd=args.repo,
                             env=env, capture_output=True, timeout=3600,
                             check=False)
        if os.path.exists(response_path):
            with open(response_path, encoding="utf-8",
                      errors="replace") as fh:
                return fh.read()
        return (out.stdout + out.stderr).decode(
            "utf-8", errors="replace")[-4000:]

    def on_round(rnd, report):
        _write_report(report, os.path.join(args.out,
                                           f"round-{rnd}"),
                      "codereview loop")

    try:
        result = core.run_loop(
            get_patch, invoke_builder, providers,
            context=args.context,
            test_runner=lambda: _run_tests(args.test_command,
                                           args.repo),
            max_rounds=args.max_rounds,
            allow_major=args.allow_major,
            strict=args.strict, on_round=on_round,
            waived_ids=args.waive)
    except _ReportWriteFailed:
        return 2
    summary = {k: v for k, v in result.items() if k != "rounds"}
    summary["rounds"] = [{"round": r["round"], "kind": r["kind"],
                          "gate": r["gate"],
                          "files": r.get("files") or [],
                          "changes_vs_previous":
                              r.get("changes_vs_previous") or {}}
                         for r in result["rounds"]]
    summary_path = os.path.join(args.out, "loop-result.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
    except OSError as exc:
        # P5-07b: the loop's outcome must survive a late write
        # failure the same way a gate report does — print the
        # final gate, park the summary in a fallback location,
        # exit 2 instead of tracebacking.
        print(f"codereview loop: writing {summary_path} "
              f"failed: {exc}", file=sys.stderr)
        print(f"codereview loop: final gate = "
              f"{result['final_gate'].upper()} — "
              f"{result['stop_reason']}")
        for fallback in (os.getcwd(), tempfile.gettempdir()):
            try:
                alt = os.path.join(fallback, "loop-result.json")
                with open(alt, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, ensure_ascii=False,
                              indent=1)
                print(f"codereview loop: summary saved to "
                      f"fallback: {alt}")
                break
            except OSError:
                continue
        return 2
    print(f"codereview loop: final gate = "
          f"{result['final_gate'].upper()} — {result['stop_reason']}")
    print(f"  rounds: {len(result['rounds'])} "
          f"(details in {args.out}/round-*/ and loop-result.json)")
    return {"pass": 0, "blocked": 1, "inconclusive": 2}.get(
        result["final_gate"], 2)


def _workflow_main(argv, providers_override=None):
    """codereview workflow — run a multi-step workflow file; each
    step is gated by the review loop and committed on approval.
    State lives in <out>/workflow-state.json (edit its `waivers`
    map to record owner waivers, then rerun to resume); touching
    <out>/STOP pauses the workflow between steps."""
    ap = argparse.ArgumentParser(prog="codereview workflow")
    ap.add_argument("--file", required=True,
                    help="workflow JSON: {name, steps: [{id, title, "
                         "agent_cmd, test_commands?}]}")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="codereview-workflow-out")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--provider", action="append", default=[])
    args = ap.parse_args(argv)

    if _refuse_unwritable_out(args.out, "codereview workflow"):
        return 2
    with open(args.file, encoding="utf-8") as fh:
        wf = json.load(fh)
    steps = wf.get("steps") or []
    if not steps:
        print("codereview: workflow file has no steps",
              file=sys.stderr)
        return 2
    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS") or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if not specs:
            print(userconfig.NOT_SET_UP, file=sys.stderr)
            return 2
        try:
            providers = build_providers(specs)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    os.makedirs(args.out, exist_ok=True)
    state_path = os.path.join(args.out, "workflow-state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)

    def save_state(s):
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1)

    result = core.run_workflow(
        steps, providers, args.repo, args.out,
        max_rounds=args.max_rounds, strict=args.strict, state=state,
        save_state=save_state,
        should_stop=lambda: os.path.exists(
            os.path.join(args.out, "STOP")))
    print(f"codereview workflow: {result['workflow_state']}")
    for s in result["steps"]:
        print(f"  step {s['id']}: {s['state']}"
              + (f" (commit {s['commit'][:10]})" if s.get("commit")
                 else "")
              + (f" — {s['error']}" if s.get("error") else ""))
    return {"complete": 0, "stopped": 1}.get(
        result["workflow_state"], 2)


def _repo_tree(repo, limit=200):
    """A shallow file listing for solver context: `git ls-files`
    when the repo is a git checkout, else a depth-limited walk.
    Returns "" when nothing useful can be listed."""
    try:
        if os.path.isdir(os.path.join(repo, ".git")):
            out = subprocess.run(
                ["git", "-C", repo, "ls-files"],
                capture_output=True, timeout=30, check=False)
            lines = out.stdout.decode("utf-8", errors="replace") \
                .splitlines()
            return "\n".join(lines[:limit])
        found = []
        for dirpath, dirnames, filenames in os.walk(repo):
            depth = os.path.relpath(dirpath, repo).count(os.sep)
            if depth > 2:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".")]
            for name in sorted(filenames):
                found.append(os.path.relpath(
                    os.path.join(dirpath, name), repo))
            if len(found) >= limit:
                break
        return "\n".join(sorted(found)[:limit])
    except Exception:  # noqa: BLE001 - the tree is optional context
        return ""


def _intake_main(argv, solvers_override=None):
    """codereview intake — issue report in, solution plan out.

    The solvers are a separate seat type from the reviewers: they
    answer in Markdown (see providers.build_solvers). The primary
    solver's plan lands in <out>/solution.md for the builder."""
    from . import intake
    from .providers import build_solvers

    ap = argparse.ArgumentParser(
        prog="codereview intake",
        description="Turn an issue report into an executable "
                    "solution plan: solver models read the report "
                    "(plus optional context files) and write the "
                    "plan a builder then implements.")
    ap.add_argument("report", help="issue report (Markdown)")
    ap.add_argument("--context", action="append", default=[],
                    help="context file to include (source files, "
                         "logs); repeatable")
    ap.add_argument("--repo", default="",
                    help="repository the report is about: its file "
                         "listing is included as context")
    ap.add_argument("--provider", action="append", default=[],
                    help="solver preset or custom spec; repeatable. "
                         "The first seat that answers is the primary. "
                         "Default: $CODEREVIEW_PROVIDERS or "
                         "gemini,nvidia")
    ap.add_argument("--role", action="append", default=[],
                    help="assign the solver role's model: "
                         "solver=<provider-spec>; the seat becomes "
                         "the primary solver, ahead of --provider "
                         "seats. Intake assigns the solver role "
                         "only")
    ap.add_argument("--timeout", type=int,
                    default=intake.DEFAULT_SOLVER_TIMEOUT,
                    help="per-solver deadline in seconds "
                         "(default 300)")
    ap.add_argument("--out", default="codereview-intake-out")
    args = ap.parse_args(argv)

    if args.timeout <= 0:
        print("codereview intake: --timeout must be a positive "
              "number of seconds", file=sys.stderr)
        return 2
    if _refuse_unwritable_out(args.out, "codereview intake"):
        return 2
    try:
        with open(os.path.expanduser(args.report), encoding="utf-8",
                  errors="replace") as fh:
            report = fh.read()
    except Exception as exc:  # noqa: BLE001
        print(f"codereview intake: could not read the report: {exc}",
              file=sys.stderr)
        return 2
    if not report.strip():
        print("codereview intake: the report is empty.",
              file=sys.stderr)
        return 2
    contexts = []
    for path in args.context:
        try:
            with open(os.path.expanduser(path), encoding="utf-8",
                      errors="replace") as fh:
                contexts.append((path, fh.read()))
        except Exception as exc:  # noqa: BLE001
            print(f"codereview intake: could not read context "
                  f"{path}: {exc}", file=sys.stderr)
            return 2

    if solvers_override is not None:
        solvers = solvers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS")
                   or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if args.role:
            try:
                assignments = registry.parse_role_assignments(
                    args.role)
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
            non_solver = sorted(r for r in assignments
                                if r != "solver")
            if non_solver:
                print(f"codereview: intake assigns the solver "
                      f"role only; got role(s): "
                      f"{', '.join(non_solver)}", file=sys.stderr)
                return 2
            if "solver" in assignments:
                specs = [assignments["solver"]] + specs
        if not specs:
            print(userconfig.NOT_SET_UP, file=sys.stderr)
            return 2
        try:
            solvers = build_solvers(specs, agent_timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: solver setup failed: {exc}",
                  file=sys.stderr)
            return 2

    result = intake.run_intake(
        report, solvers, contexts=contexts,
        repo_tree=_repo_tree(args.repo) if args.repo else "",
        timeout=args.timeout)
    solution_path, manifest_path = intake.write_intake(
        result, args.out, report_name=os.path.basename(args.report))
    print(f"codereview intake: {os.path.basename(args.report)}")
    for s in result["solutions"]:
        if s["ok"]:
            print(f"  solver {s['name']}: OK "
                  f"({s['seconds']}s, {s['chars']} chars)")
        else:
            print(f"  solver {s['name']}: FAILED — {s['error']}")
    if result["ok"]:
        print(f"  primary: {result['primary']}")
        print(f"  solution: {solution_path}")
        print(f"  data:     {manifest_path}")
        return 0
    print("  no solver produced a plan — see intake.json",
          file=sys.stderr)
    print(f"  data:     {manifest_path}")
    return 2


def _pr_main(argv, providers_override=None):
    """codereview pr — review a GitHub pull request where it lives.

    Read path works without a token on public repos. --post (review
    comment + commit status) needs GITHUB_TOKEN with repo access."""
    from .github import GitHubClient, GitHubError, parse_pr_url, \
        review_pr

    ap = argparse.ArgumentParser(prog="codereview pr")
    ap.add_argument("--repo", help="OWNER/REPO")
    ap.add_argument("--number", type=int, help="PR number")
    ap.add_argument("--pr", help="full PR URL")
    ap.add_argument("--post", action="store_true",
                    help="post the review comment + commit status "
                         "(needs GITHUB_TOKEN)")
    ap.add_argument("--request-changes", action="store_true",
                    help="use REQUEST_CHANGES when the gate blocks")
    ap.add_argument("--provider", action="append", default=[])
    ap.add_argument("--verify-previous",
                    help="previous report JSON: verification round")
    ap.add_argument("--builder-response", default="",
                    help="builder's work report (or @file)")
    ap.add_argument("--test-command", action="append", default=[])
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--allow-major", action="store_true")
    ap.add_argument("--out", default="codereview-pr-out")
    args = ap.parse_args(argv)
    if _refuse_unwritable_out(args.out, "codereview pr"):
        return 2
    try:
        if args.pr:
            owner, repo, number = parse_pr_url(args.pr)
        elif args.repo and args.number:
            owner, repo = args.repo.split("/", 1)
            number = args.number
        else:
            print("codereview pr: give --pr URL or --repo OWNER/REPO "
                  "with --number", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f"codereview pr: {exc}", file=sys.stderr)
        return 2

    if args.post and not os.environ.get("GITHUB_TOKEN", "").strip():
        # P5-02: fail fast — before providers are built, tests
        # run, or any review call is spent. (review_pr re-checks
        # at the library boundary.)
        print("codereview pr: --post needs GITHUB_TOKEN with "
              "repo access", file=sys.stderr)
        return 2

    builder_response = args.builder_response
    if builder_response.startswith("@"):
        with open(os.path.expanduser(builder_response[1:]),
                  encoding="utf-8", errors="replace") as fh:
            builder_response = fh.read()
    previous = None
    if args.verify_previous:
        with open(args.verify_previous, encoding="utf-8") as fh:
            previous = json.load(fh)

    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS") or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if not specs:
            print(userconfig.NOT_SET_UP, file=sys.stderr)
            return 2
        try:
            providers = build_providers(specs)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    test_results = _run_tests(args.test_command, ".")
    try:
        report, actions = review_pr(
            GitHubClient(), owner, repo, number, providers,
            post=args.post, request_changes=args.request_changes,
            previous=previous, builder_response=builder_response,
            test_results=test_results, strict=args.strict,
            allow_major=args.allow_major)
    except GitHubError as exc:
        print(f"codereview pr: {exc}", file=sys.stderr)
        return 2
    try:
        jpath, mpath = _write_report(report, args.out,
                                     "codereview pr")
    except _ReportWriteFailed:
        return 2
    print(f"codereview pr: {owner}/{repo}#{number} — "
          f"{report['pr']['title']}")
    print(f"  gate = {report['gate'].upper()} "
          f"({'; '.join(report.get('gate_reasons') or [])})")
    for a in actions:
        print(f"  posted: {a}")
    print(f"  report: {mpath}")
    print(f"  data:   {jpath}")
    posting = report.get("posting") or {}
    if posting.get("error"):
        # P5-03: the report above is written and names what was
        # already posted; the exit code still reflects the
        # posting failure.
        print(f"codereview pr: posting failed: {posting['error']}",
              file=sys.stderr)
        return 2
    return {"pass": 0, "blocked": 1, "inconclusive": 2}.get(
        report["gate"], 2)


_FAMILY_BY_PRESET = {"gemini": "google", "openai": "openai",
                     "xai": "xai", "nvidia": "nvidia",
                     "deepseek": "deepseek",
                     "anthropic": "anthropic",
                     "minimax": "minimax", "moonshot": "moonshot",
                     "mistral": "mistral",
                     "openrouter": "openrouter"}


def _apply_role_assignments(providers, role_values,
                            agent_timeout=None, herdr_host=None,
                            herdr_seats=None):
    """Resolve --role <role>=<provider-spec> assignments against
    the panel: each role's seat is built (once) and merged into
    `providers` if not already present, so the role's model is
    guaranteed a seat. Returns (lens_seats, seat_roles,
    role_models): lens pins for the two review lenses, the
    role -> seat-name map for the record, and the role ->
    {seat, provider, model, family} detail the record carries so
    anyone can see which model served which role. Raises
    ValueError/ProviderError on a bad assignment — callers turn
    that into exit 2, never a silent default."""
    assignments = registry.parse_role_assignments(role_values)
    lens_seats, seat_roles, role_models = {}, {}, {}
    for role, spec in assignments.items():
        desc = describe_spec(spec)
        record_model = desc["model"]
        record_family = desc["family"]
        requested_model = None
        built = build_providers([spec],
                                agent_timeout=agent_timeout,
                                herdr_host=herdr_host,
                                herdr_seats=herdr_seats)
        (seat_name, seat_fn), = built.items()
        if seat_name in providers:
            # Cross-kind collision (internal review, refutation-
            # weak finding on this seam): an agent role seat whose
            # name an API seat already owns (or the reverse) must
            # not silently record the role as served by the other
            # kind of seat. When the existing seat carries kind/
            # family tags that prove the mismatch, refuse loudly —
            # the same rule build_providers enforces inside one
            # spec list. Untagged override seats can't prove a
            # mismatch and keep the historical merge.
            existing = providers[seat_name]
            existing_tags = (
                getattr(existing, "_codereview_kind", None),
                getattr(existing, "_codereview_family", None))
            existing_is_agent = "agent" in existing_tags
            if (desc["kind"] == "agent") != existing_is_agent \
                    and any(t is not None for t in existing_tags):
                raise ProviderError(
                    f"role {role!r}: seat name {seat_name!r} is "
                    f"already used by a different kind of seat "
                    f"(agent vs API); rename the seat in the "
                    f"role spec {spec!r}")
            # Record fidelity (ratified fix, 78ddf4d5ea27): the
            # seat built from the role spec is DISCARDED here —
            # the role is served by the EXISTING seat, whose model
            # may differ from the role spec's (a pooled preset
            # seat serves its own default, not a same-name
            # override). Crediting the spec's model would record
            # a model that never serves. When the existing seat's
            # served model(s) are known (tagged at build time),
            # the record carries the SERVED model and preserves
            # the requested one alongside; a seat serving several
            # distinct models cannot honestly be credited with
            # any single one, so the assignment is refused.
            served_models = getattr(existing,
                                    "_codereview_models", None)
            if desc["model"] is not None and served_models:
                if len(served_models) > 1:
                    raise ProviderError(
                        f"role {role!r}: seat {seat_name!r} "
                        f"already exists and its accounts serve "
                        f"different models "
                        f"{list(served_models)}; the role cannot "
                        f"be credited to one model — give the "
                        f"role its own seat via a distinct spec")
                if desc["model"] != served_models[0]:
                    requested_model = desc["model"]
                    record_model = served_models[0]
                    existing_family = getattr(
                        existing, "_codereview_family", None)
                    if existing_family:
                        record_family = existing_family
        else:
            providers[seat_name] = seat_fn
        seat_roles[role] = seat_name
        role_models[role] = {
            "seat": seat_name,
            "provider": desc["preset"] or desc["kind"],
            "model": record_model,
            "family": record_family,
            "key_env": desc["key_env"],
        }
        if requested_model is not None:
            role_models[role]["requested_model"] = requested_model
        if role in registry.LENS_ROLES:
            lens_seats[registry.LENS_ROLES[role]] = seat_name
    tech_lead = seat_roles.get("tech-lead")
    return lens_seats, seat_roles, role_models, tech_lead


def _default_seat_meta(providers):
    """Baseline family tags from seat names (v0.7.3): a preset seat
    carries its vendor family; an agent seat carries the vendor
    family of the CLI it runs when that CLI is known (P6-06:
    claude -> anthropic, codex -> openai, gemini -> google,
    derived by build_providers from the seat's spec), else the
    generic family 'agent'. Tier stays 'unknown' unless tagged
    — recorded, never guessed.

    Agent seats are detected by the kind tag build_providers puts
    on the callable, NOT by name shape: resolved agent seat names
    are bare (bot, bot-2, ...) and can collide with preset names,
    so name-prefix guessing both missed suffixed agent seats and
    could tag an agent named like a preset with the preset's
    vendor family (review-v11 finding)."""
    meta = {}
    for name, fn in providers.items():
        if getattr(fn, "_codereview_kind", None) == "agent" \
                or name.startswith("agent:"):
            tagged = getattr(fn, "_codereview_family", None)
            meta[name] = {"family": tagged or "agent",
                          "tier": "unknown"}
            continue
        tagged = getattr(fn, "_codereview_family", None)
        if tagged and tagged != "unknown":
            # The registry family the seat was BUILT from wins
            # over name guessing: a seat named 'kimi' from the
            # moonshot preset is family 'moonshot'.
            meta[name] = {"family": tagged, "tier": "unknown"}
            continue
        base = name.split("-")[0].lower() if name else ""
        family = _FAMILY_BY_PRESET.get(base)
        meta[name] = {"family": family or "unknown",
                      "tier": "unknown"}
    return meta


def _parse_seat_meta(values, base=None):
    """--seat-meta name:family[:tier] entries over a baseline."""
    meta = dict(base or {})
    for value in values or []:
        parts = value.split(":")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"bad --seat-meta {value!r}: want name:family[:tier]")
        entry = dict(meta.get(parts[0]) or {})
        entry["family"] = parts[1]
        if len(parts) > 2 and parts[2]:
            entry["tier"] = parts[2]
        entry.setdefault("tier", "unknown")
        meta[parts[0]] = entry
    return meta


def _doctor_main(argv, providers_override=None,
                 fallbacks_override=None):
    ap = argparse.ArgumentParser(
        prog="codereview doctor",
        description="Preflight: probe every configured seat — "
                    "primaries AND fallbacks — with the exact "
                    "review request shape and report health as "
                    "JSON before any review runs.")
    ap.add_argument("--provider", action="append", default=[],
                    help="provider spec (same syntax as review); "
                         "repeatable. Default: $CODEREVIEW_PROVIDERS "
                         "or your saved setup (codereview setup)")
    ap.add_argument("--fallback", action="append", default=[],
                    help="fallback seat to probe too: "
                         "lens=provider-spec (same syntax as "
                         "review); repeatable")
    ap.add_argument("--role", action="append", default=[],
                    help="role seat to probe too: "
                         "<role>=<provider-spec> (same roles as "
                         "review); repeatable")
    ap.add_argument("--timeout", type=int, default=None,
                    help="per-seat timeout in seconds for agent "
                         "seats (forwarded to provider "
                         "construction, like review/intake); "
                         "also the probe's per-seat wait bound "
                         "(default: the review path's per-call "
                         "ceiling)")
    args = ap.parse_args(argv)
    if args.timeout is not None and args.timeout <= 0:
        print(json.dumps(
            {"ok": False, "seats": [],
             "error": "--timeout must be a positive number "
                      "of seconds"}))
        return 2
    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS")
                   or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if not specs:
            print(json.dumps(
                {"ok": False, "seats": [],
                 "error": "not set up: pass --provider, set "
                          "$CODEREVIEW_PROVIDERS, or run "
                          "`codereview setup`"}))
            return 2
        try:
            providers = build_providers(
                specs, agent_timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "seats": [],
                              "error": f"provider setup failed: "
                                       f"{exc}"}))
            return 2
    fallbacks = fallbacks_override
    if fallbacks is None and args.fallback:
        fallbacks = {}
        for spec in args.fallback:
            lens, eq, pspec = spec.partition("=")
            lens = lens.strip()
            if not eq or lens not in core.LENSES \
                    or not pspec.strip():
                print(json.dumps(
                    {"ok": False, "seats": [],
                     "error": f"bad --fallback {spec!r}: want "
                              f"lens=provider-spec with lens one "
                              f"of {sorted(core.LENSES)}"}))
                return 2
            try:
                built = build_providers(
                    [pspec.strip()], agent_timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001
                print(json.dumps(
                    {"ok": False, "seats": [],
                     "error": f"fallback setup failed: {exc}"}))
                return 2
            (fb_name, fb_fn), = built.items()
            if fb_name in providers:
                # Same guard as the review path (764e1d15a218):
                # a fallback that duplicates a primary seat is
                # a configuration error, not a second opinion.
                print(json.dumps(
                    {"ok": False, "seats": [],
                     "error": f"fallback seat {fb_name!r} is "
                              f"already a primary seat"}))
                return 2
            fallbacks[lens] = (fb_name, fb_fn)
    seat_roles, role_models = {}, {}
    if args.role:
        try:
            _lens, seat_roles, role_models, _tl = \
                _apply_role_assignments(
                    providers, args.role,
                    agent_timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps(
                {"ok": False, "seats": [],
                 "error": f"role assignment failed: {exc}"}))
            return 2
    result = core.run_doctor(providers, fallbacks=fallbacks,
                             timeout=args.timeout)
    if seat_roles:
        result = {**result, "seat_roles": seat_roles,
                  "role_models": role_models}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["ok"] else 2


def _timestamped_record_name(name):
    """True for write_report's record stem
    (codereview-YYYYMMDD-HHMMSS...): the filename itself carries
    the run timestamp, so name order is chronological."""
    if not name.startswith("codereview-"):
        return False
    stamp = name[len("codereview-"):]
    return (len(stamp) >= 15 and stamp[8] == "-"
            and stamp[:8].isdigit() and stamp[9:15].isdigit())


def _load_record_arg(path, repo):
    """Resolve a record argument (directory or JSON file) to
    (record, record_dir, jpath). record_dir is repo-relative —
    the head-currency checks allow later commits that touch only
    the record directories."""
    if os.path.isdir(path):
        candidates = [os.path.join(path, f)
                      for f in os.listdir(path)
                      if f.endswith(".json")]
        if not candidates:
            raise ValueError(f"no record JSON in {path}")
        stamped = [p for p in candidates
                   if _timestamped_record_name(
                       os.path.basename(p))]
        if stamped:
            # Prefer the lexicographically greatest timestamped
            # record name: name order is chronological AND
            # copy-stable, while mtime order breaks on copied or
            # re-exported record trees — and an auxiliary JSON
            # sharing the directory could otherwise outrank the
            # actual record (179ece0e030e). mtime remains the
            # fallback when no candidate carries a timestamp.
            jpath = max(stamped)
        else:
            jpath = max(candidates, key=os.path.getmtime)
        record_dir = os.path.relpath(
            os.path.abspath(path),
            os.path.abspath(repo)).replace(os.sep, "/")
    else:
        jpath = path
        record_dir = os.path.relpath(
            os.path.abspath(os.path.dirname(path) or "."),
            os.path.abspath(repo)).replace(os.sep, "/")
    with open(jpath, encoding="utf-8") as fh:
        record = json.load(fh)
    return record, record_dir, jpath


def _print_verify_result(result, label):
    for check in result["checks"]:
        mark = "ok " if check["ok"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
    for warning in result.get("warnings") or []:
        print(f"  [WARN] {warning['name']}: {warning['detail']}")
    for entry in result.get("dispositions_consumed") or []:
        print(f"  [store] disposition consumed: "
              f"{entry.get('finding_id')}: {entry.get('type')} "
              f"by {entry.get('decider')} ({entry.get('date')})")
    print(f"codereview: {label} "
          f"{'ELIGIBLE' if result['eligible'] else 'NOT eligible'}")


def _record_verify_main(argv):
    ap = argparse.ArgumentParser(
        prog="codereview record-verify",
        description="Check whether a saved review record is "
                    "eligible as a release record (clean gate, "
                    "full panel, current range).")
    ap.add_argument("path", nargs="?",
                    help="record directory or record JSON file")
    ap.add_argument("--repo", default=".",
                    help="repository the record belongs to")
    ap.add_argument("--chain", nargs="+", metavar="RECORD",
                    help="Form B: verify an ordered chain of "
                         "records (round-1 review followed by "
                         "verification rounds) as one "
                         "round-structured record. Convergence-"
                         "budget breaches are reported as WARN "
                         "lines — process flags for the owner — "
                         "and do not by themselves change the "
                         "exit code; eligibility is decided by "
                         "the checks alone.")
    ap.add_argument("--dispositions",
                    help="disposition store (JSONL) to consult "
                         "(§5.2): disputed findings with a store "
                         "entry count as dispositioned, and the "
                         "consumed entries are reported. Default: "
                         "the store at <repo>/dispositions.jsonl "
                         "when one exists; without any store, "
                         "verification behaves exactly as before.")
    args = ap.parse_args(argv)
    dispositions = None
    store_path = args.dispositions or disputes_mod.store_path_for(
        args.repo)
    if args.dispositions or os.path.isfile(store_path):
        loaded = disputes_mod.load_store(store_path)
        if loaded["problems"]:
            print("codereview: the disposition store has "
                  "problems; refusing to verify against it:",
                  file=sys.stderr)
            for problem in loaded["problems"]:
                print(f"  {problem}", file=sys.stderr)
            return 2
        dispositions = loaded["entries"]
        print(f"codereview: disposition store: "
              f"{len(dispositions)} entr(ies) from {store_path}",
              file=sys.stderr)
    try:
        if args.chain:
            records, dirs = [], []
            for p in args.chain:
                record, record_dir, _jp = _load_record_arg(
                    p, args.repo)
                records.append(record)
                dirs.append(record_dir)
            result = core.verify_chain(
                records, repo=args.repo, record_dirs=dirs,
                dispositions=dispositions)
            _print_verify_result(
                result,
                f"chain of {len(records)} record(s)")
            return 0 if result["eligible"] else 1
        if not args.path:
            ap.error("a record path is required (or --chain)")
        record, record_dir, jpath = _load_record_arg(
            args.path, args.repo)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview: could not read the record: {exc}",
              file=sys.stderr)
        return 2
    result = core.verify_record(record, repo=args.repo,
                                record_dir=record_dir,
                                dispositions=dispositions)
    _print_verify_result(result, f"record ({jpath})")
    return 0 if result["eligible"] else 1


def _disputes_main(argv):
    """codereview disputes — the computed open-dispute
    inventory (§5.1), the disposition-store append (§5.2), and
    the release-flow freshness check (§5.3)."""
    ap = argparse.ArgumentParser(
        prog="codereview disputes",
        description="Compute the open-dispute inventory from "
                    "the review records under a repo: findings "
                    "in a human-decision state (disputed or "
                    "refutation-weak) with no disposition in "
                    "the store. With --record, append one "
                    "disposition entry instead. With --check, "
                    "act as the release-flow freshness gate.")
    ap.add_argument("--repo", default=".",
                    help="repository whose review-*/ records "
                         "and disposition store are read "
                         "(default: .)")
    ap.add_argument("--store",
                    help="disposition store path (default: "
                         "<repo>/dispositions.jsonl)")
    ap.add_argument("--json", action="store_true",
                    help="print the inventory as JSON")
    ap.add_argument("--record", metavar="FILE",
                    help="append the disposition entry in FILE "
                         "(JSON object; '-' reads stdin) to the "
                         "store, with validation — a fingerprint "
                         "may be dispositioned once; a second "
                         "entry must be an override naming the "
                         "entry it supersedes")
    ap.add_argument("--check", action="store_true",
                    help="freshness gate: exit 1 listing every "
                         "open dispute in the checked records "
                         "that is neither dispositioned nor "
                         "named in the --inventory file")
    ap.add_argument("--span", metavar="A..B",
                    help="with --check: only records touching "
                         "this commit span count (default: all "
                         "records under --repo)")
    ap.add_argument("--inventory", metavar="FILE",
                    help="with --check: a caller-supplied "
                         "inventory (JSON) whose finding ids "
                         "are excused from the gate")
    ap.add_argument("--overrides", metavar="FILE",
                    help="tagger manual overrides (JSON): "
                         "{\"authority\": [ids], "
                         "\"not_authority\": [ids]}")
    args = ap.parse_args(argv)
    store_path = args.store or disputes_mod.store_path_for(
        args.repo)
    loaded = disputes_mod.load_store(store_path)
    if loaded["problems"]:
        print("codereview: the disposition store has problems:",
              file=sys.stderr)
        for problem in loaded["problems"]:
            print(f"  {problem}", file=sys.stderr)
        return 2
    entries = loaded["entries"]

    if args.record:
        try:
            raw = sys.stdin.read() if args.record == "-" else \
                open(args.record, encoding="utf-8").read()
            entry = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not read the entry: {exc}",
                  file=sys.stderr)
            return 2
        try:
            stored = disputes_mod.append_entry(store_path, entry)
        except ValueError as exc:
            print(f"codereview: entry rejected: {exc}",
                  file=sys.stderr)
            return 2
        print(f"codereview: disposition recorded: "
              f"{stored['finding_id']}: {stored['type']} by "
              f"{stored['decider']} ({stored['date']}), "
              f"entry sha256 "
              f"{disputes_mod.entry_hash(stored)[:12]}…")
        return 0

    overrides = None
    if args.overrides:
        try:
            with open(args.overrides, encoding="utf-8") as fh:
                overrides = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not read the overrides: "
                  f"{exc}", file=sys.stderr)
            return 2

    if args.check:
        inventory_ids = set()
        if args.inventory:
            try:
                inventory_ids = \
                    disputes_mod.inventory_ids_from_file(
                        args.inventory)
            except Exception as exc:  # noqa: BLE001
                print(f"codereview: could not read the "
                      f"inventory file: {exc}", file=sys.stderr)
                return 2
        if args.span:
            try:
                result = disputes_mod.check_freshness(
                    args.repo, args.repo, args.span, entries,
                    inventory_ids)
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
            scope = f"span {args.span}"
        else:
            inv = disputes_mod.build_inventory(
                args.repo, entries, overrides)
            result = {"violations": [
                row for row in inv["open"]
                if row["id"] not in inventory_ids],
                "touching": sorted({row["record"] for row in
                                    inv["open"]}),
                "unscoped": []}
            scope = "all records"
        for row in result["violations"]:
            print(f"  UNINVENTORIED {row['id']} "
                  f"({row['severity']}/{row['status']}) "
                  f"{row['record']}: {row['title']}")
        for rel in result["unscoped"]:
            print(f"  note: record {rel} carries no range/head; "
                  f"it cannot be scoped to the span and was not "
                  f"checked", file=sys.stderr)
        if result["violations"]:
            print(f"codereview: freshness check FAILED "
                  f"({scope}): {len(result['violations'])} "
                  f"open dispute(s) neither dispositioned nor "
                  f"inventoried")
            return 1
        print(f"codereview: freshness check ok ({scope}): no "
              f"un-inventoried open disputes")
        return 0

    inv = disputes_mod.build_inventory(args.repo, entries,
                                       overrides)
    if args.json:
        print(json.dumps(inv, ensure_ascii=False, indent=2))
        return 0
    by_record = {}
    for row in inv["open"]:
        by_record.setdefault(row["record"], []).append(row)
    for rel in sorted(by_record):
        print(f"{rel}:")
        for row in by_record[rel]:
            tag = row["authority"]
            raiser = (row["raiser_family"] or row["raiser"]
                      or "?")
            refuter = (row["refuter_family"] or row["refuter"]
                       or "?")
            loc = (f"{row['file']}:{row['line']}"
                   if row["line"] else row["file"])
            if tag["authority_affecting"]:
                auth = "YES — " + ", ".join(
                    tag["dimensions"] or ["(override)"])
            else:
                auth = "no"
            print(f"  {row['id']}  {row['severity']} "
                  f"{row['status']}  {loc}  "
                  f"[{raiser} -> refuted by {refuter}]")
            print(f"      {row['title']}")
            print(f"      authority-affecting: {auth}")
    n_auth = sum(1 for r in inv["open"]
                 if r["authority"]["authority_affecting"])
    print(f"codereview: {len(inv['open'])} open dispute(s) "
          f"across {inv['records_scanned']} record(s) "
          f"({n_auth} authority-affecting); "
          f"{len(inv['dispositioned'])} dispute(s) already "
          f"dispositioned in the store ({inv['store_entries']} "
          f"entr(ies) at {store_path})")
    return 0


def _locate_main(argv):
    """codereview locate <finding-id> --record <path> — resolve
    a finding's validated quote to its blob position(s) at the
    reviewed commit (§5.6)."""
    ap = argparse.ArgumentParser(
        prog="codereview locate",
        description="Resolve a finding's validated evidence "
                    "quote to its position(s) in the cited file "
                    "as committed at the record's reviewed "
                    "commit. The quote is the anchor; the cited "
                    "line number is only checked against it.")
    ap.add_argument("finding_id",
                    help="the finding's fingerprint (id)")
    ap.add_argument("--record", required=True,
                    help="record directory or record JSON file")
    ap.add_argument("--repo", default=".",
                    help="repository the record belongs to")
    args = ap.parse_args(argv)
    try:
        record, record_dir, jpath = _load_record_arg(
            args.record, args.repo)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview: could not read the record: {exc}",
              file=sys.stderr)
        return 2
    result = disputes_mod.locate_finding(
        record, args.finding_id, args.repo, record_dir)
    if result is None:
        print(f"codereview: finding {args.finding_id} is not in "
              f"{jpath}", file=sys.stderr)
        return 2
    print(f"finding {result['finding_id']}: {result['title']}")
    print(f"  file: {result['file']}  cited line: "
          f"{result['cited_line']}  line_basis: "
          f"{result['line_basis'] or '(not recorded)'}")
    print(f"  quote ({result['quote_source']}, from "
          f"{result['quote_from']}): {result['quote'][:200]}")
    if result["blob_error"]:
        print(f"  blob at {result['blob_ref']}: unreadable — "
              f"{result['blob_error']}")
        return 1
    if not result["positions"]:
        print(f"  quote not found in {result['file']} at "
              f"{result['blob_ref'][:12]}… — the citation does "
              f"not resolve at the reviewed commit")
        return 1
    print(f"  blob positions at {result['blob_ref'][:12]}…: "
          f"{result['positions']}")
    resolves = ("yes" if result["cited_matches"] else
                "NO — the numbering basis differs "
                "(see line_basis)")
    print(f"  cited line resolves: {resolves}")
    return 0


def _sarif_main(argv):
    """codereview sarif — export a saved record's open findings
    as a SARIF 2.1.0 log (Epic D, ticket D1), for GitHub code
    scanning and other SARIF consumers. An export, not a gate:
    exit 0 means the log was written, whatever the record's
    gate was; exit 2 means the record could not be read."""
    ap = argparse.ArgumentParser(
        prog="codereview sarif",
        description="Export a saved review record as SARIF "
                    "2.1.0 (open findings only; see "
                    "codereview.sarif for the mapping).")
    ap.add_argument("path",
                    help="record directory or record JSON file")
    ap.add_argument("--repo", default=".",
                    help="repository the record belongs to")
    ap.add_argument("--out",
                    help="write the SARIF log here "
                         "(default: stdout)")
    args = ap.parse_args(argv)
    try:
        record, _record_dir, jpath = _load_record_arg(
            args.path, args.repo)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview: could not read the record: {exc}",
              file=sys.stderr)
        return 2
    log = sarif_mod.record_to_sarif(record)
    text = json.dumps(log, ensure_ascii=False, indent=2) + "\n"
    run = log["runs"][0]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"codereview sarif: {jpath} -> {args.out} "
              f"({len(run['results'])} result(s), "
              f"{len(run['tool']['driver']['rules'])} rule(s); "
              f"record gate = "
              f"{str(record.get('gate') or 'unknown').upper()})")
    else:
        sys.stdout.write(text)
    return 0


def _mcp_main(argv):
    """codereview mcp serve — serve the gate over the Model
    Context Protocol (Epic L2): a stdio server exposing
    run_gate / get_verdict so an MCP-speaking agent can invoke
    the gate from inside its own loop. Serving only — the
    server is a front door onto this same CLI (a run goes
    through main() itself), holds no credentials of its own,
    and draws seats only from the saved setup / environment,
    exactly like a CLI run. Protocol on stdout; all
    diagnostics on stderr."""
    if argv and argv[0] in ("-h", "--help"):
        ap = argparse.ArgumentParser(
            prog="codereview mcp",
            description="Serve the CodeReview gate over the "
                        "Model Context Protocol.")
        ap.add_argument("action", choices=("serve",),
                        help="serve — serve the gate on stdio "
                             "(tools: run_gate, get_verdict)")
        ap.parse_args(argv)
    if not argv or argv[0] != "serve":
        print("usage: codereview mcp serve", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(
        prog="codereview mcp serve",
        description="Serve the CodeReview gate over MCP "
                    "(stdio transport; tools: run_gate, "
                    "get_verdict).")
    ap.parse_args(argv[1:])
    from . import mcp_tools
    print(f"codereview mcp: serving the gate on stdio "
          f"(server {mcp_tools.SERVER_INFO['name']} "
          f"{mcp_tools.SERVER_INFO['version']}; seats from "
          f"your saved setup)", file=sys.stderr)
    mcp_tools.serve_stdio()
    return 0


def _policy_main(argv):
    """codereview policy check — validate the project's policy
    file (.codereview.toml, Epic B) and print the effective
    policy: the file's rules with every default filled in. With
    no policy file, the effective policy is the defaults — no
    requirements — and that is a valid state, printed as such."""
    if argv and argv[0] in ("-h", "--help"):
        ap = argparse.ArgumentParser(
            prog="codereview policy",
            description="Validate and print the effective "
                        "project policy.")
        ap.add_argument("action", choices=("check",),
                        help="check — validate the policy file "
                             "and print the effective policy")
        ap.parse_args(argv)
    if not argv or argv[0] != "check":
        print("usage: codereview policy check [--repo DIR] "
              "[--policy PATH]", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(
        prog="codereview policy check",
        description="Validate the project policy file and print "
                    "the effective policy (defaults filled in).")
    ap.add_argument("--repo", default=".",
                    help="repository root (default: .); the "
                         "policy file is .codereview.toml there")
    ap.add_argument("--policy",
                    help="policy file path (default: "
                         "<repo>/.codereview.toml)")
    args = ap.parse_args(argv[1:])
    path = args.policy or os.path.join(
        args.repo, policy_mod.POLICY_FILENAME)
    if not os.path.exists(path):
        print(f"codereview policy: no policy file at {path} — "
              f"the default policy is in effect (no "
              f"requirements):")
        print(policy_mod.render_effective(
            policy_mod.default_policy()))
        return 0
    try:
        loaded = policy_mod.load_policy(path)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview policy: {exc}", file=sys.stderr)
        return 2
    print(f"codereview policy: {path} is valid "
          f"(sha256 {loaded['sha256'][:12]}…). Effective policy:")
    print(policy_mod.render_effective(loaded))
    return 0


def _bench_main(argv, providers_override=None):
    """codereview bench run|report — Epic A benchmark harness."""
    if argv and argv[0] in ("-h", "--help"):
        ap = argparse.ArgumentParser(
            prog="codereview bench",
            description="Run the benchmark corpus and "
                        "reports (Epic A harness).")
        ap.add_argument("action", choices=("run", "report"),
                        help="run — run the corpus under a "
                             "config; report — summarise saved "
                             "results")
        ap.parse_args(argv)
    if not argv or argv[0] not in ("run", "report"):
        print("usage: codereview bench run --config NAME [...] "
              "[--corpus DIR] [--out DIR] [--split all|public|holdout]\n"
              "       codereview bench report [--results DIR] "
              "[--corpus DIR] [--public] [--out-dir DIR]\n"
              "              [--max-escaped-rate RATE]",
              file=sys.stderr)
        return 2
    action, rest = argv[0], argv[1:]
    if action == "run":
        ap = argparse.ArgumentParser(prog="codereview bench run")
        ap.add_argument("--config", action="append", required=True,
                        help="config name (bench/configs/<name>.json) "
                             "or path to a config JSON; repeatable")
        ap.add_argument("--corpus", default="bench/corpus",
                        help="corpus directory (default: bench/corpus)")
        ap.add_argument("--out", default="bench-out",
                        help="results directory (default: bench-out); "
                             "runs resume — recorded cases are skipped")
        ap.add_argument("--split", default="all",
                        choices=["all", "public", "holdout"],
                        help="restrict to one corpus split")
        ap.add_argument("--force", action="store_true",
                        help="discard existing results for the named "
                             "configs and re-run every case")
        args = ap.parse_args(rest)
        if _refuse_unwritable_out(args.out, "codereview bench"):
            return 2
        injected = None
        if providers_override is not None:
            injected = {}
            for spec in args.config:
                try:
                    name = bench_mod.load_config(
                        bench_mod.resolve_config_path(
                            spec, args.corpus))["name"]
                except Exception:  # noqa: BLE001
                    continue
                injected[name] = providers_override
        try:
            results = bench_mod.run_bench(
                args.corpus, args.config, args.out, split=args.split,
                force=args.force, providers_by_config=injected)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview bench: {exc}", file=sys.stderr)
            return 2
        for name, records in results.items():
            gates = {}
            for rec in records:
                gates[rec["gate"]] = gates.get(rec["gate"], 0) + 1
            print(f"codereview bench: {name}: {len(records)} case "
                  f"record(s) in {args.out} "
                  f"(gates: {json.dumps(gates, sort_keys=True)})")
        return 0
    ap = argparse.ArgumentParser(prog="codereview bench report")
    ap.add_argument("--results", default="bench-out",
                    help="results directory written by bench run "
                         "(default: bench-out)")
    ap.add_argument("--corpus", default="bench/corpus",
                    help="corpus directory (default: bench/corpus)")
    ap.add_argument("--public", action="store_true",
                    help="public report: holdout split excluded "
                         "before scoring (ids and rows never appear)")
    ap.add_argument("--out-dir",
                    help="also write bench-report.md and "
                         "bench-report.json here")
    ap.add_argument("--max-escaped-rate", type=float,
                    help="exit 1 if any config's escaped-defect rate "
                         "exceeds this rate (CI regression gate)")
    args = ap.parse_args(rest)
    if _refuse_unwritable_out(args.out_dir, "codereview bench"):
        return 2
    try:
        report = bench_mod.build_report(
            bench_mod.load_results(args.results), args.corpus,
            public_only=args.public)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview bench: {exc}", file=sys.stderr)
        return 2
    md = bench_mod.render_markdown(report)
    print(md)
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        stem = "bench-report-public" if args.public else "bench-report"
        with open(os.path.join(args.out_dir, stem + ".md"), "w",
                  encoding="utf-8") as fh:
            fh.write(md)
        with open(os.path.join(args.out_dir, stem + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"codereview bench: wrote {stem}.md / {stem}.json "
              f"to {args.out_dir}")
    if args.max_escaped_rate is not None:
        worst = [(name, e["metrics"]["escaped_defect_rate"])
                 for name, e in report["configs"].items()
                 if e["metrics"]["escaped_defect_rate"] is not None
                 and e["metrics"]["escaped_defect_rate"]
                 > args.max_escaped_rate]
        if worst:
            for name, rate in worst:
                print(f"codereview bench: {name} escaped-defect rate "
                      f"{rate:.3f} exceeds --max-escaped-rate "
                      f"{args.max_escaped_rate}", file=sys.stderr)
            return 1
    return 0


def _acceptance_main(argv, providers_override=None):
    """codereview acceptance — run the shadow Tech Lead over
    the known-answer acceptance corpus and score the adopted
    gates M1–M6 (refutation-process solution §6). The seat is
    built from --provider specs (or supplied by the caller via
    providers_override, as the swarm runner supplies its
    seats); its family must be a third family relative to the
    corpus's raiser/refuter families for the run to mean
    anything."""
    ap = argparse.ArgumentParser(prog="codereview acceptance")
    ap.add_argument("--corpus", required=True,
                    help="path to the acceptance corpus "
                         "directory (index.json + cases/ + "
                         "scorecard.json + mutations.json)")
    ap.add_argument("--provider", action="append", default=[],
                    help="provider spec for the Tech Lead seat, "
                         "e.g. deepseek:deepseek-chat (the "
                         "first seat is used)")
    ap.add_argument("--seat-family", default=None,
                    help="family tag for the seat (defaults to "
                         "the seat's provider family)")
    ap.add_argument("--out", default=None,
                    help="write the full run record (JSON) to "
                         "this directory")
    ap.add_argument("--no-mutations", action="store_true",
                    help="skip the M4 mutation battery")
    ap.add_argument("--timeout", type=int, default=180,
                    help="per-call timeout in seconds")
    args = ap.parse_args(argv)
    if providers_override:
        seats = dict(providers_override)
    elif args.provider:
        try:
            seats = build_providers(
                args.provider, agent_timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2
    else:
        print("codereview: acceptance needs a seat: pass "
              "--provider <spec>", file=sys.stderr)
        return 2
    if not seats:
        print("codereview: no seat available", file=sys.stderr)
        return 2
    seat_name, seat_fn = next(iter(seats.items()))
    seat_family = args.seat_family or getattr(
        seat_fn, "_codereview_family", None) or seat_name
    from . import acceptance as acceptance_mod
    result = acceptance_mod.run_acceptance(
        args.corpus, seat_fn, seat_family=seat_family,
        seat_name=seat_name,
        do_mutations=not args.no_mutations,
        timeout=args.timeout,
        log=lambda m: print(m, file=sys.stderr))
    for mid, m in result["metrics"].items():
        print(f"{mid}: measured={m['measured']} "
              f"threshold={m['threshold']} "
              f"pass={m['pass']}")
    print(f"unlock (all gates on one run): "
          f"{result['unlock_all_gates_pass']}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, "acceptance-run.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, default=str)
        print(f"record: {path}")
    return 0 if result["unlock_all_gates_pass"] else 1


def _seat_progress(event):
    """Live seat-state line (Epic K2): one stderr line per seat
    transition while a review/verification round runs, so a
    seat stuck on its plan's quota, a login, or a stall is
    visible as it happens — the same transitions the record
    persists per seat (seat_state). A seat that ends blocked
    on quota gets the spec's operator guidance; the panel's
    degraded handling itself is the gate's, unchanged."""
    state = event.get("state") or ""
    cls = event.get("class")
    label = f"{state}:{cls}" if cls else state
    print(f"codereview: seat {event.get('seat')}: {label}",
          file=sys.stderr)
    if event.get("terminal") and state == "blocked" \
            and cls == "quota":
        print(f"codereview: seat {event.get('seat')} hit its "
              f"plan's allowance; the panel continues degraded "
              f"— top up or wait for the reset.", file=sys.stderr)


def main(argv=None, providers_override=None, seat_meta_override=None,
         fallbacks_override=None):
    # P3-04: the gate process holds provider keys in its
    # environment and runs untrusted commands (evidence,
    # probes, agent seats); make it non-dumpable so a child
    # cannot read that environment back via /proc/$PPID.
    hardening.make_non_dumpable()
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "setup":
        return _setup_main(argv[1:])
    if argv and argv[0] == "evidence":
        return _evidence_main(argv[1:])
    if argv and argv[0] == "acceptance":
        return _acceptance_main(
            argv[1:], providers_override=providers_override)
    if argv and argv[0] == "doctor":
        return _doctor_main(argv[1:],
                            providers_override=providers_override,
                            fallbacks_override=fallbacks_override)
    if argv and argv[0] == "record-verify":
        return _record_verify_main(argv[1:])
    if argv and argv[0] == "policy":
        return _policy_main(argv[1:])
    if argv and argv[0] == "sarif":
        return _sarif_main(argv[1:])
    if argv and argv[0] == "disputes":
        return _disputes_main(argv[1:])
    if argv and argv[0] == "locate":
        return _locate_main(argv[1:])
    if argv and argv[0] == "bench":
        return _bench_main(argv[1:],
                           providers_override=providers_override)
    if argv and argv[0] == "pr":
        return _pr_main(argv[1:],
                        providers_override=providers_override)
    if argv and argv[0] == "workflow":
        return _workflow_main(argv[1:],
                              providers_override=providers_override)
    if argv and argv[0] == "loop":
        return _loop_main(argv[1:],
                          providers_override=providers_override)
    if argv and argv[0] == "intake":
        return _intake_main(argv[1:],
                            solvers_override=providers_override)
    if argv and argv[0] == "mcp":
        return _mcp_main(argv[1:])
    ap = argparse.ArgumentParser(
        prog="codereview",
        description="Multi-model code review loop with a "
                    "deterministic gate.",
        epilog="Subcommands (each has its own --help; running "
               "one replaces the review flags above): "
               "setup — first-run wizard: pick providers, keys "
               "and per-role models; "
               "doctor — probe the configured seats; "
               "policy — validate and print the effective "
               "project policy; "
               "record-verify — verify a stored run record "
               "offline; "
               "disputes — list and record rulings on disputed "
               "findings; "
               "bench — run the benchmark corpus and reports; "
               "intake — turn an issue report into a reviewed "
               "solution; "
               "pr — review a GitHub pull request in place; "
               "workflow — run a saved multi-step review "
               "workflow; "
               "loop — repeat review rounds until the gate "
               "passes; "
               "sarif — export a record's findings as SARIF; "
               "evidence — run an evidence config standalone; "
               "locate — resolve a cited quote to blob "
               "positions; "
               "acceptance — run the acceptance harness; "
               "mcp — serve the gate over the Model Context "
               "Protocol (stdio; run_gate / get_verdict).")
    ap.add_argument("--version", action="version",
                    version=core.VERSION,
                    help="print the codereview version and exit")
    src = ap.add_argument_group("change source (pick one)")
    src.add_argument("--patch", help="unified diff file")
    src.add_argument("--repo", help="git repository path (default: .)")
    src.add_argument("--range", dest="range",
                     help="git diff range, e.g. main...HEAD")
    src.add_argument("--staged", action="store_true",
                     help="review the staged diff")
    src.add_argument("--files", nargs="+",
                     help="review these files in full (new files)")
    ap.add_argument("--provider", action="append", default=[],
                    help="provider preset (openai, gemini, anthropic, "
                         "deepseek, minimax, moonshot, nvidia, xai, "
                         "mistral, openrouter; preset:model to pick "
                         "the model) or name|type|base_url|model|"
                         "key_env; repeatable. Default: "
                         "$CODEREVIEW_PROVIDERS or your saved setup "
                         "(codereview setup)")
    ap.add_argument("--context", default="",
                    help="builder's change description (or @file)")
    ap.add_argument("--test-command", action="append", default=[],
                    help="test command to run and include; repeatable")
    ap.add_argument("--evidence-config",
                    help="evidence runner config (JSON; Epic C): "
                         "configured test/lint/SAST commands and "
                         "security adapters run in a sandboxed copy "
                         "of the tree (scrubbed environment, no "
                         "network by default), the hashed evidence "
                         "record is stored in the report, and "
                         "required evidence that fails BLOCKS the "
                         "gate (unavailable required evidence is "
                         "INCONCLUSIVE). The config's shape matches "
                         "the Epic B policy file's [evidence] table")
    ap.add_argument("--out", default="codereview-out",
                    help="output directory for the report (default: "
                         "codereview-out)")
    ap.add_argument("--allow-major", action="store_true",
                    help="only blockers block the gate (majors advisory)")
    ap.add_argument("--strict", action="store_true",
                    help="degraded or truncated reviews are INCONCLUSIVE "
                         "instead of passing")
    ap.add_argument("--gate-profile",
                    choices=("strict", "balanced", "corroborated"),
                    default=None,
                    help="gate profile: 'strict' (the default — "
                         "every blocking-severity finding blocks), "
                         "'balanced' (policy B1: a blocking "
                         "finding raised solely by the operations "
                         "lens, with no correctness-lens or "
                         "deterministic corroboration in the "
                         "merged finding, is demoted to a visible "
                         "minor), or 'corroborated' (policy B2: "
                         "evidence-class blocking for every lens "
                         "— a blocking finding needs deterministic, "
                         "probe-confirmed, or cross-family-"
                         "corroborated evidence, plus a validated "
                         "quote and a concrete trigger; "
                         "single-source findings become visible "
                         "non-blocking unverified majors. Requires "
                         "at least two distinct vendor families "
                         "able to serve the correctness lens; "
                         "single-family panels keep 'strict'. B2 "
                         "is opt-in and unconfirmed — dev "
                         "evidence only). Overrides the policy "
                         "file's [gate] profile; the policy file "
                         "overrides the default. The default "
                         "stays 'strict'")
    ap.add_argument("--max-patch-chars", type=int, default=80000,
                    help="per-batch diff budget (default 80000)")
    ap.add_argument("--no-file-context", action="store_true",
                    help="do not attach post-change file contents "
                         "to the reviewer prompts (default for "
                         "repo reviews: the contents of each "
                         "changed file — from the range target, "
                         "the index, or the working tree — ride "
                         "along as reference so definitions "
                         "outside the diff hunks can be checked; "
                         "capped per file and in total, with "
                         "truncation marked in the text and "
                         "listed in the record)")
    ap.add_argument("--no-agents-context", action="store_true",
                    help="do not ingest AGENTS.md project "
                         "guidance into the reviewer prompts "
                         "(default for repo reviews: AGENTS.md at "
                         "the repo root and nested along the "
                         "changed paths is attached as advisory, "
                         "untrusted context alongside — never "
                         "instead of — .codereview.toml; its "
                         "'## Code Review Rules' section is "
                         "surfaced as rules the panel may cite; "
                         "redacted, capped per file and in total "
                         "with truncation recorded, provenance "
                         "(path + sha256) written to the record)")
    ap.add_argument("--verify-previous",
                    help="previous report JSON: run a verification round")
    ap.add_argument("--builder-response", default="",
                    help="builder's response to prior findings (or @file)")
    ap.add_argument("--role", action="append", default=[],
                    help="assign a model to a role: "
                         "<role>=<provider-spec> with role one of "
                         "correctness, operations, verifier, "
                         "tech-lead, solver (e.g. "
                         "tech-lead=deepseek:deepseek-reasoner, "
                         "correctness=moonshot); repeatable. The "
                         "role's seat joins the panel and the "
                         "assignment is recorded in the report")
    ap.add_argument("--seat-meta", action="append", default=[],
                    help="tag a seat for the record: name:family[:tier] "
                         "(e.g. gemini:google:paid); repeatable")
    ap.add_argument("--fallback", action="append", default=[],
                    help="fallback seat for a lens when its primary "
                         "fails: lens=provider-spec (e.g. "
                         "correctness=openai); repeatable")
    ap.add_argument("--fixture-manifest",
                    help="versioned fixture manifest (JSON): the "
                         "enumerated paths are intentionally "
                         "vulnerable test DATA — their findings are "
                         "classified in the record as expected "
                         "fixture findings instead of blocking the "
                         "gate. The manifest's hash, policy version "
                         "and paths are recorded and recomputed by "
                         "record-verify")
    ap.add_argument("--precedents",
                    help="content-addressed precedent store "
                         "(JSON): findings already adjudicated "
                         "whose cited file is UNCHANGED (git blob "
                         "identical to the disposition) are "
                         "classified in the record as standing "
                         "findings linked to their disposition "
                         "instead of blocking again. The store's "
                         "hash and every link are recorded and "
                         "recomputed by record-verify")
    ap.add_argument("--policy",
                    help="project policy file (TOML, Epic B): the "
                         "panel, evidence, path and waiver rules "
                         "the gate enforces for this repository. "
                         "Default: .codereview.toml at the repo "
                         "root, when present. An invalid policy "
                         "file stops the run — it is never "
                         "silently ignored")
    ap.add_argument("--trust-repo-policy", action="store_true",
                    help="honour a policy DISCOVERED in the "
                         "reviewed repository in full, including "
                         "its [hooks] and gate-weakening keys. "
                         "Without this flag a discovered policy "
                         "keeps only its strengthening keys: "
                         "hooks, a weaker-than-strict gate "
                         "profile, advisory path rules, waiver "
                         "leniency, diversity degrade/exclusion "
                         "and risk tiering are ignored and named "
                         "in the record's policy.ignored_keys "
                         "(P3-01 trust restriction). A policy "
                         "named with --policy is always honoured "
                         "in full")
    ap.add_argument("--tech-lead",
                    help="designate the seat that serves as Tech "
                         "Lead for adjudicating refuted findings "
                         "(owner amendment 2026-11-04): the Tech "
                         "Lead's family must be independent of "
                         "both the finding's raiser and its "
                         "refuter — a designation that cannot "
                         "serve independently is rejected and "
                         "substituted, loudly, on the record. "
                         "Without a designation, the first "
                         "independent seat serves")
    ap.add_argument("--tech-lead-shadow", action="store_true",
                    help="run the Tech Lead in SHADOW mode: for "
                         "every disputed finding the full "
                         "structured adjudication is produced and "
                         "recorded in the record's "
                         "shadow_adjudications section — blinded "
                         "A/B positions, double-drawn for majors "
                         "— but the decisions are non-binding and "
                         "never change the gate verdict. The seat "
                         "is the --tech-lead seat when designated, "
                         "else an independent seat, else any "
                         "served seat under reduced independence. "
                         "Equivalent to the CODEREVIEW_TECH_LEAD_"
                         "SHADOW=1 environment variable")
    ap.add_argument("--attempts-log",
                    help="append one JSON line describing this run "
                         "(seats, error classes, gate) to this file. "
                         "Trust level: operator-supplied — the path "
                         "comes from the command line only, never "
                         "from repo content, policy, or config files "
                         "(same trust as --out)")
    ap.add_argument("--private", action="store_true",
                    help="the repository is private: seats tagged "
                         "with a free tier are refused (free tiers "
                         "may train on submitted code)")
    ap.add_argument("--timeout", type=int, default=None,
                    help="per-seat timeout in seconds for agent "
                         "seats (forwarded to provider construction "
                         "for primary AND fallback seats, like "
                         "doctor/intake); also the wait bound for "
                         "Tech Lead adjudication calls")
    ap.add_argument("--probe-timeout", type=int, default=120,
                    help="wall-clock bound in seconds for one "
                         "harness probe (default 120)")
    ap.add_argument("--no-probe-harness", action="store_true",
                    help="do not wire the probe harness: a Tech "
                         "Lead probe request then escalates for "
                         "lack of a channel, as before the "
                         "harness existed")
    args = ap.parse_args(argv)

    if args.timeout is not None and args.timeout <= 0:
        print("codereview: --timeout must be a positive number "
              "of seconds", file=sys.stderr)
        return 2
    if _refuse_unwritable_out(args.out, "codereview"):
        return 2

    # P3-09: an explicitly given --repo must be a real
    # directory. "" used to collapse to "." via `or`, and a
    # nonexistent path was accepted in BOTH modes — in patch
    # mode the run then silently skipped all project context
    # (policy, AGENTS.md, evidence) and still passed.
    if args.repo is not None:
        if args.repo == "":
            print("codereview: --repo must not be empty "
                  "(omit it to review the current directory)",
                  file=sys.stderr)
            return 2
        if not os.path.isdir(args.repo):
            print(f"codereview: --repo {args.repo!r} is not "
                  f"an existing directory", file=sys.stderr)
            return 2

    def _maybe_file(text):
        if text.startswith("@"):
            with open(os.path.expanduser(text[1:]), encoding="utf-8",
                      errors="replace") as fh:
                return fh.read()
        return text

    try:
        patch = _load_patch(args)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview: could not load the change: {exc}",
              file=sys.stderr)
        return 2
    fixture_scope = None
    if args.fixture_manifest:
        try:
            fixture_scope = _load_fixture_scope(
                args.fixture_manifest, repo=args.repo or ".")
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not load the fixture "
                  f"manifest: {exc}", file=sys.stderr)
            return 2
        print(f"codereview: fixture scope: "
              f"{len(fixture_scope['patterns'])} path(s) from "
              f"{fixture_scope['manifest_path']} (policy "
              f"v{fixture_scope['policy_version']}, sha256 "
              f"{fixture_scope['manifest_sha256'][:12]}…) — "
              f"fixture findings will be classified separately, "
              f"not dropped", file=sys.stderr)
    precedents = None
    if args.precedents:
        try:
            precedents = _load_precedents(
                args.precedents, repo=args.repo or ".")
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not load the precedent "
                  f"store: {exc}", file=sys.stderr)
            return 2
        print(f"codereview: precedent store: "
              f"{len(precedents['entries'])} entr(ies) from "
              f"{precedents['store_path']} (sha256 "
              f"{precedents['store_sha256'][:12]}…) — standing "
              f"findings will be classified separately, not "
              f"dropped", file=sys.stderr)
    project_policy = None
    policy_path = args.policy
    # P3-01: a policy DISCOVERED in the reviewed repo is
    # repo-supplied configuration. The origin is stamped on
    # the policy, lands in the record's policy section, and a
    # discovered policy warns on stderr. And since the owner's
    # 2026-11-06 ruling (option 1), a discovered policy is no
    # longer applied in full: unless the operator passes
    # --trust-repo-policy, the restriction in policy.py drops
    # its hooks and gate-weakening keys back to defaults HERE,
    # at load — before the hook runner is built from the
    # policy below and before the gate reads it — and names
    # every dropped key on the record (policy.ignored_keys).
    policy_origin = "explicit" if policy_path is not None \
        else None
    if policy_path is None:
        discovered = policy_mod.find_policy(args.repo or ".")
        if discovered:
            policy_path = discovered
            policy_origin = "discovered-in-repo"
    if policy_path:
        try:
            project_policy = policy_mod.load_policy(policy_path)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not load the project "
                  f"policy: {exc}", file=sys.stderr)
            return 2
        project_policy["origin"] = policy_origin
        ignored_keys = []
        if policy_origin == "discovered-in-repo" \
                and not args.trust_repo_policy:
            ignored_keys = policy_mod \
                .apply_discovered_restrictions(project_policy)
        print(f"codereview: project policy: "
              f"{len(project_policy['paths'])} path rule(s) from "
              f"{policy_path} — the gate enforces it and the "
              f"record lists every rule applied",
              file=sys.stderr)
        if policy_origin == "discovered-in-repo":
            print(f"codereview: WARNING: that policy was "
                  f"discovered in the reviewed repository "
                  f"({policy_path}) — it comes from the tree "
                  f"under review, not from the operator; the "
                  f"record's policy section states this origin",
                  file=sys.stderr)
            if ignored_keys:
                print(f"codereview: WARNING: "
                      f"{len(ignored_keys)} gate-weakening "
                      f"key(s) in that policy were ignored "
                      f"under the discovered-policy trust "
                      f"restriction ({', '.join(ignored_keys)}) "
                      f"— pass --trust-repo-policy to honour "
                      f"the repository's policy in full",
                      file=sys.stderr)
    # Epic L3: lifecycle hooks from the policy's [hooks] table.
    # The runner is created here (no side effects) and fired at
    # the lifecycle points below; with no [hooks] commands it
    # stays None and the run is exactly as before. Hooks run
    # sandboxed (Epic C) and can never change the verdict.
    hook_runner = None
    if project_policy is not None:
        _hooks_config = hooks_mod.hooks_from_policy(
            project_policy)
        if _hooks_config is not None:
            hook_runner = hooks_mod.HookRunner(
                _hooks_config, args.repo or ".")
            print(f"codereview: lifecycle hooks: "
                  f"{', '.join(hook_runner.configured_events())} "
                  f"configured in {policy_path} — sandboxed, "
                  f"recorded in the record's hooks section, "
                  f"never gate-changing", file=sys.stderr)
    if not patch.strip():
        print("codereview: the change is empty — nothing to review.",
              file=sys.stderr)
        return 2

    # Epic K3a hosting state for this run (set in the specs
    # branch below): an active HerdrHost plus the config-marked
    # seat names, or the inert reason the record carries as one
    # `herdr_hosting` line. Override providers (bench, internal
    # runner) are never hosted.
    herdr_host = None
    herdr_seats = None
    herdr_inert = None
    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = (os.environ.get("CODEREVIEW_PROVIDERS") or os.environ.get("REVIEWLOOP_PROVIDERS", ""))
            try:
                specs = [s.strip() for s in env.split(",")
                         if s.strip()] \
                    or userconfig.default_provider_specs()
            except ValueError as exc:
                print(f"codereview: {exc}", file=sys.stderr)
                return 2
        if not specs and _stdin_is_tty():
            # First open in a terminal: run the setup wizard,
            # then use what the user just saved as their setup.
            # An aborted wizard (EOF / Ctrl-C) is a clean stop,
            # never a traceback: fall through to not-set-up.
            try:
                _run_setup_wizard()
                specs = userconfig.default_provider_specs()
            except (ValueError, EOFError,
                    KeyboardInterrupt) as exc:
                print(f"codereview: setup did not complete "
                      f"({exc}); nothing was run.",
                      file=sys.stderr)
                return 2
        if not specs:
            print(userconfig.NOT_SET_UP, file=sys.stderr)
            return 2
        # Epic K3a: seats the saved config marks for herdr
        # hosting ([hosting] herdr = [...]) are detected ONCE
        # for the run. An active detection hosts those seats;
        # an inert one leaves every seat headless and puts ONE
        # line in the record (record_extra below) — herdr is
        # never a hard dependency.
        try:
            herdr_seats = userconfig.default_hosting_herdr_seats()
        except ValueError as exc:
            print(f"codereview: {exc}", file=sys.stderr)
            return 2
        if herdr_seats:
            plan = herdrhost.detect()
            if plan["active"]:
                herdr_host = plan["host"]
            else:
                herdr_inert = herdrhost.inert_line(plan)
                herdr_seats = None
        try:
            providers = build_providers(
                specs, agent_timeout=args.timeout,
                herdr_host=herdr_host, herdr_seats=herdr_seats)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    lens_seats, seat_roles, role_models, tech_lead_seat = {}, {}, {}, None
    try:
        _config_roles = userconfig.default_role_assignments()
    except ValueError as exc:
        print(f"codereview: {exc}", file=sys.stderr)
        return 2
    if args.role or _config_roles:
        try:
            _cli_roles = registry.parse_role_assignments(args.role)
        except ValueError as exc:
            print(f"codereview: {exc}", file=sys.stderr)
            return 2
        _merged_roles = {**_config_roles, **_cli_roles}
        try:
            lens_seats, seat_roles, role_models, tech_lead_seat = \
                _apply_role_assignments(
                    providers,
                    [f"{r}={spec}" for r, spec
                     in _merged_roles.items()],
                    agent_timeout=args.timeout,
                    herdr_host=herdr_host,
                    herdr_seats=herdr_seats)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: role assignment failed: {exc}",
                  file=sys.stderr)
            return 2

    # Seat metadata precedence: the derived baseline, then
    # the saved setup's [seat_meta] (P6-06 — the families the
    # wizard computed for this panel), then explicit
    # --seat-meta, then the caller's override below.
    try:
        saved_meta = userconfig.default_seat_meta()
    except ValueError as exc:
        print(f"codereview: {exc}", file=sys.stderr)
        return 2
    baseline_meta = _default_seat_meta(providers)
    for _name, _family in saved_meta.items():
        if _name in baseline_meta and _family:
            baseline_meta[_name] = {
                "family": _family,
                "tier": baseline_meta[_name].get(
                    "tier", "unknown")}
    try:
        seat_meta = _parse_seat_meta(
            args.seat_meta, baseline_meta)
    except ValueError as exc:
        print(f"codereview: {exc}", file=sys.stderr)
        return 2
    if seat_meta_override:
        seat_meta.update(seat_meta_override)
    violations = core.check_tier_policy(seat_meta,
                                        private=args.private)
    if violations:
        for violation in violations:
            print(f"codereview: tier policy: {violation}",
                  file=sys.stderr)
        return 2

    fallbacks = fallbacks_override
    if fallbacks is None and args.fallback:
        fallbacks = {}
        for spec in args.fallback:
            lens, eq, pspec = spec.partition("=")
            lens = lens.strip()
            if not eq or lens not in core.LENSES or not pspec.strip():
                print(f"codereview: bad --fallback {spec!r}: want "
                      f"lens=provider-spec with lens one of "
                      f"{sorted(core.LENSES)}", file=sys.stderr)
                return 2
            try:
                built = build_providers(
                    [pspec.strip()], agent_timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"codereview: fallback setup failed: {exc}",
                      file=sys.stderr)
                return 2
            (fb_name, fb_fn), = built.items()
            if fb_name in providers:
                print(f"codereview: fallback seat {fb_name!r} is "
                      f"already a primary seat", file=sys.stderr)
                return 2
            fallbacks[lens] = (fb_name, fb_fn)

    record_extra = None
    if args.range:
        record_extra = {"range": args.range}
        try:
            record_extra["head"] = core._git(
                args.repo or ".", "rev-parse", "HEAD")
        except Exception:  # noqa: BLE001 — head is best-effort
            pass
    if seat_roles:
        # Which model served which role is part of the record
        # (owner directive 2026-11-04): seat name, provider,
        # model, and family for every assigned role.
        record_extra = {**(record_extra or {}),
                        "seat_roles": seat_roles,
                        "role_models": role_models}
    if herdr_inert:
        # Epic K3a: hosting was configured but the adapter
        # stayed inert — exactly one line in the record says
        # why; the seats all ran headless.
        record_extra = {**(record_extra or {}),
                        "herdr_hosting": herdr_inert}


    cwd = args.repo or "."
    test_results = _run_tests(args.test_command, cwd)

    review_kwargs = {}
    if not args.no_probe_harness:
        # Probe harness (refutation-process solution §5.2):
        # the Tech Lead's probe channel, wired by default so a
        # needs_probe decision no longer auto-escalates for
        # lack of a channel. Probes execute in the harness
        # sandbox against a temp copy of the reviewed tree —
        # never in the tree itself, never with the process
        # environment. The swarm internal runner reaches this
        # same wiring through cli.main.
        from . import probe as probe_mod
        review_kwargs["probe_fn"] = probe_mod.make_probe_fn(
            args.repo or ".", timeout=args.probe_timeout)
    if lens_seats:
        review_kwargs["lens_seats"] = lens_seats
    if tech_lead_seat and "tech_lead" in \
            inspect.signature(core.run_review).parameters:
        # Tech Lead designation seam: when the engine carries the
        # adjudication role (step4 design), hand the designated
        # seat over — the engine itself enforces the independence
        # rule (its family must differ from raiser and refuter)
        # and substitutes loudly when the designee is ineligible.
        # Until the seam lands, the assignment travels in the
        # record's seat_roles only.
        review_kwargs["tech_lead"] = tech_lead_seat
    if args.tech_lead:
        # The explicit --tech-lead flag designates the same role a
        # --role/saved-setup assignment can; the command line wins
        # (the same precedence --role has over the saved setup).
        review_kwargs["tech_lead"] = args.tech_lead
    if args.evidence_config:
        # Epic C: run the evidence config against a sandboxed
        # copy of the tree and attach the record to the review;
        # run_review stores it in the report and applies the C3
        # gate rule. Verification rounds keep their own gate
        # semantics and do not take evidence (review_kwargs only
        # reaches run_review).
        try:
            evidence_cfg = evidence_mod.load_config(
                args.evidence_config)
        except ValueError as exc:
            print(f"codereview: {exc}", file=sys.stderr)
            return 2
        review_kwargs["evidence"] = evidence_mod.collect(
            evidence_cfg, cwd)
    shadow_role_seat = seat_roles.get("tech-lead-shadow")
    if args.tech_lead_shadow or shadow_role_seat or os.environ.get(
            "CODEREVIEW_TECH_LEAD_SHADOW") == "1":
        # Shadow Tech Lead: recorded, non-binding, gate-neutral
        # (the engine guarantees verdict invariance). Seat
        # precedence: an explicit tech-lead-shadow role, then
        # the binding --tech-lead designation, then the engine's
        # own independent-seat choice.
        review_kwargs["tech_lead_shadow"] = True
        shadow_seat = shadow_role_seat or args.tech_lead \
            or tech_lead_seat
        if shadow_seat:
            review_kwargs["tech_lead_shadow_seat"] = shadow_seat

    file_context = None
    if not args.verify_previous and not args.patch \
            and not args.files and not args.no_file_context:
        # Acceptance D1: attach the post-change contents of the
        # changed files so reviewers can check definitions the
        # hunks reference but do not contain. A collection
        # problem degrades to the old diff-only behaviour with
        # the reason on stderr — context is an aid, never a
        # reason to fail a review.
        try:
            file_context, fc_entries = core.collect_file_context(
                args.repo or ".", patch, range_spec=args.range,
                staged=args.staged)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: file context unavailable "
                  f"({exc}); reviewing the diff alone",
                  file=sys.stderr)
            file_context = None
        if file_context is not None:
            attached = [e for e in fc_entries
                        if e.get("sent_chars")]
            skipped = [e for e in fc_entries if e.get("skipped")]
            notes = []
            for e in fc_entries:
                if e.get("truncated"):
                    notes.append(
                        f"{e['file']} truncated "
                        f"({e['truncated']})")
            print(f"codereview: file context: "
                  f"{len(attached)} file(s) attached "
                  f"({sum(e['sent_chars'] for e in attached)} "
                  f"chars), {len(skipped)} skipped"
                  + (f"; {'; '.join(notes)}" if notes else ""),
                  file=sys.stderr)
            if not file_context:
                file_context = None

    agents_context = None
    if not args.verify_previous and not args.patch \
            and not args.files and not args.no_agents_context:
        # Epic L1: ingest the repository's AGENTS.md guidance
        # (root + nested along the changed paths) as advisory
        # reviewer context. The files are untrusted: the
        # collector redacts them, run_review delimits them as
        # data in the prompt, and their provenance lands in the
        # record — they never touch the policy, the panel, or
        # the gate. A collection problem degrades to no guidance
        # with the reason on stderr, exactly like file context.
        try:
            agents_context, ag_entries = \
                agentsmd.collect_agents_context(
                    args.repo or ".", patch)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: AGENTS.md context unavailable "
                  f"({exc}); reviewing without project guidance",
                  file=sys.stderr)
            agents_context = None
        if agents_context is not None:
            skipped = [e for e in ag_entries if e.get("skipped")]
            print(f"codereview: AGENTS.md context: "
                  f"{len(agents_context['files'])} file(s) "
                  f"ingested ({agents_context['total_chars']} "
                  f"chars), {len(skipped)} skipped"
                  + ("; truncation recorded"
                     if agents_context["truncated"] else ""),
                  file=sys.stderr)

    # Epic L4: attention notifications resolve from the USER
    # SETUP's [notify] table only — never the project policy
    # (notifications are operator preference, not project
    # contract). Unset means no Notifier at all, and the run
    # behaves exactly as before this epic.
    notify = notify_mod.notifier_for(
        userconfig.default_notify_command())

    if hook_runner is not None:
        # Epic L3 pre-run: every setup step has succeeded and
        # the run is committed — the next thing that happens is
        # the round's first seat call.
        hook_runner.fire("pre-run")

    if args.verify_previous:
        try:
            with open(args.verify_previous, encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not read previous report: {exc}",
                  file=sys.stderr)
            return 2
        builder_response = _maybe_file(args.builder_response)
        report = core.run_verification(
            patch, providers, previous,
            builder_response,
            test_results=test_results,
            max_patch_chars=args.max_patch_chars,
            allow_major=args.allow_major, strict=args.strict,
            seat_meta=seat_meta, fallbacks=fallbacks,
            record_extra=record_extra,
            private=args.private, progress=_seat_progress,
            notify=notify)
        # Epic C4: verify the builder report's claimed commands
        # against the tree and record the outcome in the run
        # record. This runs after the gate has been decided and
        # nothing reads the section back — claim verification
        # is evidence, not a gate input: a mismatch downgrades
        # the claim, never the verdict (claims.BOUNDARY).
        claim_section = claims_mod.verify_report_claims(
            builder_response, args.repo or ".")
        if claim_section is not None:
            report["claim_verification"] = claim_section
    else:
        report = core.run_review(
            patch, providers, context=_maybe_file(args.context),
            test_results=test_results,
            max_patch_chars=args.max_patch_chars,
            allow_major=args.allow_major, strict=args.strict,
            seat_meta=seat_meta, fallbacks=fallbacks,
            record_extra=record_extra,
            fixture_scope=fixture_scope, private=args.private,
            precedents=precedents, policy=project_policy,
            gate_profile=args.gate_profile,
            file_context=file_context, progress=_seat_progress,
            agents_context=agents_context, notify=notify,
            tech_lead_timeout=args.timeout, **review_kwargs)

    if policy_origin == "discovered-in-repo" \
            and not args.verify_previous and not args.range:
        # P3-01(c), working-tree half: `git diff` never shows
        # an untracked or modified .codereview.toml as a patch
        # section, so run_review's section-based
        # policy_self_modification flag cannot see the common
        # case — the applied policy file is itself part of the
        # uncommitted change. Ask git about the file directly.
        try:
            _pol_status = core._git(
                args.repo or ".", "status", "--porcelain",
                "--", policy_mod.POLICY_FILENAME)
        except Exception:  # noqa: BLE001 — the flag is
            # best-effort observability, never a run failure.
            _pol_status = ""
        if _pol_status.strip():
            _touched = report.setdefault(
                "policy_self_modification", [])
            if policy_mod.POLICY_FILENAME not in _touched:
                report["policy_self_modification"] = sorted(
                    _touched + [policy_mod.POLICY_FILENAME])

    if hook_runner is not None:
        # Epic L3: the blocked trigger is a fact of the finished
        # round; the record is written WITH the hooks section
        # (configured events, trigger, pre-run result) so the
        # post-record hooks are handed a file that already
        # carries all of it.
        hook_runner.blocked_trigger = \
            hooks_mod.first_blocked_trigger(
                report.get("reviewer_reports"))
        report["hooks"] = hook_runner.section()
    try:
        jpath, mpath = _write_report(report, args.out, "codereview")
    except _ReportWriteFailed:
        return 2
    if hook_runner is not None:
        # The record now exists: on-blocked (only when a seat
        # blocked) and post-verdict fire with its path. Their
        # results are appended to the hooks section and the
        # record is rewritten once at the same path, so the
        # file the hooks received is the file carrying the
        # complete hooks ledger.
        if hook_runner.blocked_trigger is not None:
            hook_runner.fire("on-blocked", record_path=jpath)
        hook_runner.fire("post-verdict", record_path=jpath)
        report["hooks"] = hook_runner.section()
        try:
            jpath, mpath = _write_report(
                report, args.out, "codereview",
                stem=os.path.basename(jpath)[:-len(".json")])
        except _ReportWriteFailed:
            return 2
    if args.attempts_log:
        try:
            entry = {
                "ts": core._now_iso(), "mode": report.get("mode"),
                "gate": report.get("gate"),
                "degraded": report.get("degraded"),
                "range": args.range,
                "patch_sha256": report.get("patch_sha256"),
                "seats": [{
                    "provider": r.get("provider"),
                    "lens": r.get("lens"),
                    "status": r.get("status"),
                    "family": r.get("family"),
                    "tier": r.get("tier"),
                    "fallback_for": r.get("fallback_for"),
                    "attempts": r.get("attempts"),
                    "error_class": (r.get("error_classes")
                                    or [""])[-1],
                } for r in report.get("reviewer_reports") or []],
                "tests_ok": (all(t.get("ok") for t in test_results)
                             if test_results else None),
            }
            with open(args.attempts_log, "a",
                      encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — bookkeeping never breaks
            pass
    n_block = sum(1 for f in report.get("findings") or []
                  if f["severity"] in ("blocker", "major"))
    print(f"codereview: gate = {report['gate'].upper()} "
          f"({'; '.join(report.get('gate_reasons') or [])})")
    print(f"  findings: {len(report.get('findings') or [])} "
          f"({n_block} blocking-severity)")
    open_disputes = report.get("open_disputes") or {}
    if open_disputes.get("count"):
        print(f"  open disputes: {open_disputes['count']} "
              f"({', '.join(open_disputes.get('ids') or [])}) "
              f"— see `codereview disputes`")
    print(f"  report: {mpath}")
    print(f"  data:   {jpath}")
    return {"pass": 0, "blocked": 1, "inconclusive": 2}.get(
        report["gate"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
