#!/usr/bin/env python3
"""CodeReview herdr plugin launcher.

Thin by design: the review engine lives in the installed
`codereview` CLI (pip package `codereview-ai`). This script only

  1. locates `codereview` on PATH — if it is absent, prints the
     install hint and exits non-zero *before doing anything
     else*, so the failure has no side effects;
  2. works out which repository is "the current workspace"
     (explicit --repo, else the workspace cwd herdr injects via
     HERDR_PLUGIN_CONTEXT_JSON, else the process cwd when the
     launcher is run by hand outside herdr);
  3. reads the plugin's optional config (policy / out) from
     HERDR_PLUGIN_CONFIG_DIR/config.toml;
  4. runs the gate with the workspace as cwd, streaming its
     output through, and exits with the gate's own exit code
     (0 PASS, 1 BLOCKED, 2 INCONCLUSIVE / error).

The launcher stores no credentials, makes no network calls,
and writes nothing itself — the only files a run creates are
CodeReview's own outputs under the reviewed workspace.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib

INSTALL_HINT = (
    "codereview: the `codereview` CLI is not installed.\n"
    "Install it with:\n"
    "    pip install codereview-ai\n"
    "then run `codereview setup` once to choose your review "
    "panel, and try again."
)


def _context_workspace_cwd(environ):
    """The workspace cwd from herdr's invocation context.

    HERDR_PLUGIN_CONTEXT_JSON carries `workspace_cwd` (the
    focused pane's cwd, or the workspace's default cwd) plus
    `focused_pane_cwd` and a `worktree` object with
    `checkout_path`. First non-empty string wins; any malformed
    context is ignored (returns None) rather than fatal.
    """
    raw = environ.get("HERDR_PLUGIN_CONTEXT_JSON") or ""
    if not raw.strip():
        return None
    try:
        context = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(context, dict):
        return None
    for key in ("workspace_cwd", "focused_pane_cwd"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    worktree = context.get("worktree")
    if isinstance(worktree, dict):
        value = worktree.get("checkout_path")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _resolve_repo(args_repo, environ):
    """-> (repo_path, error_message). Exactly one is set."""
    if args_repo:
        return os.path.abspath(args_repo), None
    cwd = _context_workspace_cwd(environ)
    if cwd:
        return os.path.abspath(cwd), None
    if environ.get("HERDR_PLUGIN_ID"):
        # Running as a herdr plugin but herdr gave us no
        # workspace cwd: guessing (our cwd is the plugin
        # directory) would review the wrong tree. Fail loudly.
        return None, (
            "codereview: herdr provided no workspace directory "
            "for this invocation, so there is nothing safe to "
            "review. Invoke the action from a workspace pane, "
            "or run `codereview --repo <path>` by hand.")
    return os.getcwd(), None


def _plugin_config(environ):
    """Optional config.toml in HERDR_PLUGIN_CONFIG_DIR.

    Recognised keys: `policy` (path to a .codereview.toml to
    pass through as --policy; relative paths resolve against
    the reviewed workspace) and `out` (report output directory
    name passed through as --out). A missing or malformed file
    never blocks the run: malformed warns once on stderr and
    the run continues unconfigured.
    """
    config_dir = environ.get("HERDR_PLUGIN_CONFIG_DIR") or ""
    if not config_dir:
        return {}
    path = os.path.join(config_dir, "config.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError) as exc:
        print(f"codereview: ignoring malformed plugin config "
              f"{path}: {exc}", file=sys.stderr)
        return {}
    config = {}
    for key in ("policy", "out"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            config[key] = value
    return config


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        prog="codereview-launch",
        description="Run the CodeReview gate on the current "
                    "workspace (herdr plugin launcher).")
    parser.add_argument("--repo",
                        help="repository to review (default: the "
                             "herdr workspace cwd, else the "
                             "current directory)")
    parser.add_argument("--pane", action="store_true",
                        help="invoked from the plugin's overlay "
                             "pane: on a terminal, wait for Enter "
                             "after the run so the verdict stays "
                             "readable")
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="extra arguments after `--` are "
                             "passed through to the codereview CLI")
    args = parser.parse_args(argv)

    # The missing-codereview check comes first, before any
    # other work: this failure path must have no side effects.
    codereview = shutil.which("codereview", path=environ.get("PATH"))
    if codereview is None:
        print(INSTALL_HINT, file=sys.stderr)
        return 127

    repo, error = _resolve_repo(args.repo, environ)
    if error is not None:
        print(error, file=sys.stderr)
        return 2
    if not os.path.isdir(repo):
        print(f"codereview: workspace directory does not "
              f"exist: {repo}", file=sys.stderr)
        return 2

    passthrough = list(args.extra)
    if passthrough[:1] == ["--"]:
        passthrough = passthrough[1:]

    config = _plugin_config(environ)
    cmd = [codereview, "--repo", repo]
    if "policy" in config:
        policy = config["policy"]
        if not os.path.isabs(policy):
            policy = os.path.join(repo, policy)
        cmd += ["--policy", policy]
    if "out" in config:
        cmd += ["--out", config["out"]]
    cmd += passthrough

    print(f"codereview: reviewing {repo}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=repo)
        rc = proc.returncode
    except KeyboardInterrupt:
        rc = 130
    if rc < 0:  # killed by a signal: report the shell convention
        rc = 128 - rc

    if args.pane and sys.stdin.isatty():
        try:
            input("codereview: press Enter to close ")
        except (EOFError, KeyboardInterrupt):
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
