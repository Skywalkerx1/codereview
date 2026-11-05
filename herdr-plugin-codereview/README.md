# CodeReview for herdr (plugin)

A thin herdr plugin that puts the **CodeReview** gate one
keystroke away from the workspace you are already looking at:
the action runs the multi-model review gate against the
current workspace's uncommitted changes and prints the verdict
and the path of the run record.

CodeReview is an independent product. The gate itself — the
reviewer panel, the deterministic gate, the records — lives in
the pip package; this plugin is only a launcher. It contains
no review logic, stores no credentials, and makes no network
calls of its own. (A gate run talks to whichever providers
*your own* CodeReview setup names, under your own keys/logins,
exactly as a hand-run `codereview` would.)

## Requirements

- herdr 0.9.0 or newer.
- Python 3.11+ on `PATH` (as `python3`).
- CodeReview installed:

  ```bash
  pip install codereview-ai
  codereview setup   # once: choose your reviewer panel
  ```

  Without the CLI, the action prints the install hint and
  exits non-zero; it never pretends a review happened.

## Install

The herdr marketplace listing is pending (the marketplace
indexes GitHub repositories, and CodeReview's GitHub home is
currently unavailable). Until then, install from a local copy
— a clone of any CodeReview mirror (GitLab, Codeberg) or an
unpacked PyPI sdist both work:

```bash
herdr plugin link /path/to/codereview/herdr-plugin-codereview
herdr plugin action list --plugin superstartelecom.codereview
```

## Use

- Run **CodeReview: review current workspace** from the
  workspace's action menu. It reviews the working tree against
  `HEAD` (staged, unstaged, and untracked changes), streams the
  run, and ends with the gate line plus the record paths:

  ```text
  codereview: gate = PASS (...)
    findings: 0 (0 blocking-severity)
    report: .../codereview-out/codereview-<timestamp>.md
    data:   .../codereview-out/codereview-<timestamp>.json
  ```

  The action's exit code is the gate's: 0 = PASS, 1 = BLOCKED,
  2 = INCONCLUSIVE or an error setting up the run.

- The **CodeReview review** overlay pane runs the same review
  and waits for Enter before closing, so the verdict stays
  readable.

- Optional keybinding (add to your own herdr config; the
  plugin suggests, never forces):

  ```toml
  [[keys.command]]
  key = "prefix+r"
  type = "plugin_action"
  command = "superstartelecom.codereview.review-workspace"
  description = "CodeReview: review current workspace"
  ```

## Optional configuration

If `config.toml` exists in the plugin's config directory
(`herdr plugin config-dir superstartelecom.codereview`), the
launcher reads two keys:

```toml
# .codereview.toml to pass to every run (relative paths
# resolve against the reviewed workspace)
policy = ".codereview.toml"

# report output directory (default: codereview's own default)
out = "codereview-out"
```

That file is the plugin's only configuration. Nothing else is
stored: no credentials, no state — run records live in the
reviewed workspace's output directory, where CodeReview
always puts them.

## Run it by hand

The launcher is an ordinary script; outside herdr it reviews
the current directory:

```bash
python3 codereview_launch.py [--repo PATH] [-- extra codereview args...]
```
