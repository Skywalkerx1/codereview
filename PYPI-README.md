# codereview-loop

**One agent builds. Independent models review. A deterministic gate decides.**

CodeReview is a multi-model review gate for AI-written code. A panel of models from different providers reviews each change, cross-checks each other's findings, and a deterministic gate issues a recorded PASS / BLOCKED / INCONCLUSIVE verdict, so the model that wrote the code is never the only one that checked it. It ships as a command-line tool (`codereview`) and an MCP server, so your coding agents can submit their own work to the gate before it merges.

You bring your own API keys and choose the models for each role. Your code goes only to the providers you choose.

> **Status: alpha (0.13 line).** Read "Read this first" below before you rely on the default profile.

## Read this first

The default `strict` gate is deliberately unforgiving. In registered confirmation testing it caught every seeded defect (recall 1.00, 7 of 7; Wilson 95% interval [0.646, 1.000]) at 0.583 merged blocking precision (95% interval [0.320, 0.807]; a derived paired-row figure), **and it blocked 94% of clean changes (32 of 34; 95% interval [0.809, 0.984])**. The registered confirmation **failed** its clean-change threshold. (Registered confirmation record: bench/generation-v2/RESULTS-2026-11-05.md.)

That is the trade: `strict` is a high-recall gate for code you cannot afford to get wrong, with a documented waiver path for blocks you choose to accept. Expect to review and waive blocks on clean changes.

## What has been tested

- An agent-CLI seat, tested with Codex.
- The MCP server, driven end to end by a real agent client (Codex CLI): a defective sample and a clean sample were both blocked under the default `strict` profile.
- Patch review on a real GitLab merge-request diff.

Not yet tested: the pull-request command on a live PR. Reviewers are models; they miss things and occasionally invent them, so your own tests stay part of the gate.

## Install

```bash
pip install codereview-loop
codereview --version
```

The installed command is `codereview`. Requires Python 3.11 or newer; no third-party dependencies.

## Quick start

```bash
export GEMINI_API_KEY=...        # any two providers are a good start
export OPENAI_API_KEY=...

# Review the staged diff in the current repo
codereview --repo . --staged --provider gemini --provider openai

# Review a patch file with your tests as an input
codereview --patch change.diff \
  --provider gemini --provider xai \
  --test-command "python -m pytest -q" \
  --context "Adds retry logic to the payment webhook handler"

echo $?   # 0 = PASS, 1 = BLOCKED, 2 = INCONCLUSIVE
```

`codereview setup` saves your provider choices. The report is written to `codereview-out/` as Markdown plus a JSON verdict record.

## If something goes wrong

- `codereview --version`, then re-run the failing command.
- `codereview support-bundle` writes one redacted zip you can attach to an issue.
- A crash prints one line, writes a redacted note and exits with code 2.
- Security problems: do not open a public issue; see the Security link below.

## Privacy

Feedback is opt-in. Nothing leaves your machine because of these features unless you run `codereview report` and confirm, or turn on the optional anonymous crash ping with `codereview telemetry enable` (off by default). What each sends is in the privacy notice.

## Links

- Source and releases: https://gitlab.com/superstartelecom/codereview
- Release notes: https://gitlab.com/superstartelecom/codereview/-/releases/v0.13.1
- Issues: https://gitlab.com/superstartelecom/codereview/-/issues
- Security policy: https://gitlab.com/superstartelecom/codereview/-/blob/master/SECURITY.md
- Privacy notice: https://gitlab.com/superstartelecom/codereview/-/blob/master/PRIVACY.md
- Full documentation: https://gitlab.com/superstartelecom/codereview/-/blob/master/README.md
- Support: support@phpatch.com

## License

MIT. Published by Superstar Telecom LLC.
