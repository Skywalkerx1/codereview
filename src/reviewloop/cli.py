#!/usr/bin/env python3
"""reviewloop CLI.

Examples:
  reviewloop --repo . --staged --provider gemini --provider openai
  reviewloop --patch change.diff --provider xai --provider gemini \
      --test-command "python -m pytest -q"
  reviewloop --patch fix.diff --verify-previous report.json \
      --builder-response response.md --provider gemini --provider nvidia

Exit codes: 0 = gate PASS, 1 = gate BLOCKED, 2 = INCONCLUSIVE or
usage/infrastructure error.
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


def main(argv=None, providers_override=None):
    ap = argparse.ArgumentParser(
        prog="reviewloop",
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
                         "repeatable. Default: $REVIEWLOOP_PROVIDERS or "
                         "gemini,openai")
    ap.add_argument("--context", default="",
                    help="builder's change description (or @file)")
    ap.add_argument("--test-command", action="append", default=[],
                    help="test command to run and include; repeatable")
    ap.add_argument("--out", default="reviewloop-out",
                    help="output directory for the report (default: "
                         "reviewloop-out)")
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
        print(f"reviewloop: could not load the change: {exc}",
              file=sys.stderr)
        return 2
    if not patch.strip():
        print("reviewloop: the change is empty — nothing to review.",
              file=sys.stderr)
        return 2

    if providers_override is not None:
        providers = providers_override
    else:
        specs = args.provider
        if not specs:
            env = os.environ.get("REVIEWLOOP_PROVIDERS", "")
            specs = [s.strip() for s in env.split(",") if s.strip()] \
                or ["gemini", "openai"]
        try:
            providers = build_providers(specs)
        except Exception as exc:  # noqa: BLE001
            print(f"reviewloop: provider setup failed: {exc}",
                  file=sys.stderr)
            return 2

    cwd = args.repo or "."
    test_results = _run_tests(args.test_command, cwd)

    if args.verify_previous:
        try:
            with open(args.verify_previous, encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"reviewloop: could not read previous report: {exc}",
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
    print(f"reviewloop: gate = {report['gate'].upper()} "
          f"({'; '.join(report.get('gate_reasons') or [])})")
    print(f"  findings: {len(report.get('findings') or [])} "
          f"({n_block} blocking-severity)")
    print(f"  report: {mpath}")
    print(f"  data:   {jpath}")
    return {"pass": 0, "blocked": 1, "inconclusive": 2}.get(
        report["gate"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
