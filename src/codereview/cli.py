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
import json
import os
import subprocess
import sys

from . import core
from .providers import build_providers


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
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "openai"]
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
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "openai"]
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
    ap.add_argument("--timeout", type=int,
                    default=intake.DEFAULT_SOLVER_TIMEOUT,
                    help="per-solver deadline in seconds "
                         "(default 300)")
    ap.add_argument("--out", default="codereview-intake-out")
    args = ap.parse_args(argv)

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
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "nvidia"]
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
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "openai"]
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


def main(argv=None, providers_override=None):
    if argv is None:
        argv = sys.argv[1:]
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
                    help="provider preset (gemini, openai, xai, nvidia, "
                         "deepseek) or name|type|base_url|model|key_env; "
                         "repeatable. Default: $CODEREVIEW_PROVIDERS or "
                         "gemini,openai")
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
    args = ap.parse_args(argv)

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
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "openai"]
        try:
            providers = build_providers(specs)
        except Exception as exc:  # noqa: BLE001
            print(f"codereview: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    cwd = args.repo or "."
    test_results = _run_tests(args.test_command, cwd)

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
            allow_major=args.allow_major, strict=args.strict)
    else:
        report = core.run_review(
            patch, providers, context=_maybe_file(args.context),
            test_results=test_results,
            max_patch_chars=args.max_patch_chars,
            allow_major=args.allow_major, strict=args.strict)

    jpath, mpath = core.write_report(report, args.out)
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
