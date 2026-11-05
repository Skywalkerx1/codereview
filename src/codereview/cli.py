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

import inspect

from . import bench as bench_mod
from . import core
from . import registry
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


def _is_within(path, root):
    """True when `path` resolves inside `root` — failing closed.

    os.path.commonpath raises ValueError for paths on different
    drives (Windows) or when mixing absolute and relative paths;
    a containment question that cannot be evaluated is a
    containment failure, never a pass (v0.9.6, disputed findings
    eae8137a6db3 / 3cecf66f6ce5: the mechanism was real, the
    severity was not — one shared helper, used at both loader
    call sites, so the two cannot drift apart again)."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False


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


def _run_setup_wizard():
    """The first-run wizard (test seam): the CLI wires the live
    seat probe; tests substitute this to script a setup."""
    return setup_wizard.run_wizard(
        probe_fn=lambda providers: core.run_doctor(providers))


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
        core.write_report(report, os.path.join(args.out,
                                               f"round-{rnd}"))

    result = core.run_loop(
        get_patch, invoke_builder, providers, context=args.context,
        test_runner=lambda: _run_tests(args.test_command, args.repo),
        max_rounds=args.max_rounds, allow_major=args.allow_major,
        strict=args.strict, on_round=on_round,
        waived_ids=args.waive)
    summary = {k: v for k, v in result.items() if k != "rounds"}
    summary["rounds"] = [{"round": r["round"], "kind": r["kind"],
                          "gate": r["gate"],
                          "files": r.get("files") or [],
                          "changes_vs_previous":
                              r.get("changes_vs_previous") or {}}
                         for r in result["rounds"]]
    with open(os.path.join(args.out, "loop-result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
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
    jpath, mpath = core.write_report(report, args.out)
    print(f"codereview pr: {owner}/{repo}#{number} — "
          f"{report['pr']['title']}")
    print(f"  gate = {report['gate'].upper()} "
          f"({'; '.join(report.get('gate_reasons') or [])})")
    for a in actions:
        print(f"  posted: {a}")
    print(f"  report: {mpath}")
    print(f"  data:   {jpath}")
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
                            agent_timeout=None):
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
        built = build_providers([spec],
                                agent_timeout=agent_timeout)
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
        else:
            providers[seat_name] = seat_fn
        seat_roles[role] = seat_name
        role_models[role] = {
            "seat": seat_name,
            "provider": desc["preset"] or desc["kind"],
            "model": desc["model"],
            "family": desc["family"],
            "key_env": desc["key_env"],
        }
        if role in registry.LENS_ROLES:
            lens_seats[registry.LENS_ROLES[role]] = seat_name
    tech_lead = seat_roles.get("tech-lead")
    return lens_seats, seat_roles, role_models, tech_lead


def _default_seat_meta(providers):
    """Baseline family tags from seat names (v0.7.3): a preset seat
    carries its vendor family; an agent seat is family 'agent'.
    Tier stays 'unknown' unless tagged — recorded, never guessed.

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
            meta[name] = {"family": "agent", "tier": "unknown"}
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


def _load_record_arg(path, repo):
    """Resolve a record argument (directory or JSON file) to
    (record, record_dir, jpath). record_dir is repo-relative —
    the head-currency checks allow later commits that touch only
    the record directories."""
    if os.path.isdir(path):
        candidates = sorted(
            (os.path.join(path, f) for f in os.listdir(path)
             if f.endswith(".json")),
            key=lambda p: os.path.getmtime(p))
        if not candidates:
            raise ValueError(f"no record JSON in {path}")
        jpath = candidates[-1]
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
    args = ap.parse_args(argv)
    try:
        if args.chain:
            records, dirs = [], []
            for p in args.chain:
                record, record_dir, _jp = _load_record_arg(
                    p, args.repo)
                records.append(record)
                dirs.append(record_dir)
            result = core.verify_chain(records, repo=args.repo,
                                       record_dirs=dirs)
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
                                record_dir=record_dir)
    _print_verify_result(result, f"record ({jpath})")
    return 0 if result["eligible"] else 1


def _bench_main(argv, providers_override=None):
    """codereview bench run|report — Epic A benchmark harness."""
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


def main(argv=None, providers_override=None, seat_meta_override=None,
         fallbacks_override=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "setup":
        return _setup_main(argv[1:])
    if argv and argv[0] == "acceptance":
        return _acceptance_main(
            argv[1:], providers_override=providers_override)
    if argv and argv[0] == "doctor":
        return _doctor_main(argv[1:],
                            providers_override=providers_override,
                            fallbacks_override=fallbacks_override)
    if argv and argv[0] == "record-verify":
        return _record_verify_main(argv[1:])
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
    ap = argparse.ArgumentParser(
        prog="codereview",
        description="Multi-model code review loop with a "
                    "deterministic gate.")
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
    ap.add_argument("--out", default="codereview-out",
                    help="output directory for the report (default: "
                         "codereview-out)")
    ap.add_argument("--allow-major", action="store_true",
                    help="only blockers block the gate (majors advisory)")
    ap.add_argument("--strict", action="store_true",
                    help="degraded or truncated reviews are INCONCLUSIVE "
                         "instead of passing")
    ap.add_argument("--max-patch-chars", type=int, default=80000,
                    help="per-batch diff budget (default 80000)")
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
    if not patch.strip():
        print("codereview: the change is empty — nothing to review.",
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
        try:
            providers = build_providers(
                specs, agent_timeout=args.timeout)
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
                    agent_timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: role assignment failed: {exc}",
                  file=sys.stderr)
            return 2

    try:
        seat_meta = _parse_seat_meta(
            args.seat_meta, _default_seat_meta(providers))
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

    if args.verify_previous:
        try:
            with open(args.verify_previous, encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: could not read previous report: {exc}",
                  file=sys.stderr)
            return 2
        report = core.run_verification(
            patch, providers, previous,
            _maybe_file(args.builder_response),
            test_results=test_results,
            max_patch_chars=args.max_patch_chars,
            allow_major=args.allow_major, strict=args.strict,
            seat_meta=seat_meta, fallbacks=fallbacks,
            record_extra=record_extra,
            private=args.private)
    else:
        report = core.run_review(
            patch, providers, context=_maybe_file(args.context),
            test_results=test_results,
            max_patch_chars=args.max_patch_chars,
            allow_major=args.allow_major, strict=args.strict,
            seat_meta=seat_meta, fallbacks=fallbacks,
            record_extra=record_extra,
            fixture_scope=fixture_scope, private=args.private,
            precedents=precedents,
            tech_lead_timeout=args.timeout, **review_kwargs)

    jpath, mpath = core.write_report(report, args.out)
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
    print(f"  report: {mpath}")
    print(f"  data:   {jpath}")
    return {"pass": 0, "blocked": 1, "inconclusive": 2}.get(
        report["gate"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
