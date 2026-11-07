# Privacy

**Nothing leaves your machine because of this tool's feedback
features unless you ask for it.**

CodeReview sends your diff to the model providers you configured,
with your own keys, to do its job. That is separate from everything
below.

## What can be sent to the CodeReview project

| Feature | When it sends | What |
|---|---|---|
| `codereview report` | Only after you have seen the contents and confirmed (or passed `--yes`) | The redacted support bundle: identity (version, Python, OS), package list, which provider variables are set (names only), redacted config and policy, your message, and, unless you pass `--no-records`, the latest run record and crash notes |
| Crash ping | Only if you ran `codereview telemetry enable` (or set `CODEREVIEW_TELEMETRY=1`) | Version, git hash, Python version, OS family and architecture, command name, exception type, module and function of the crash, exit code, a random install id |

## What is never sent

Code, diffs, findings, file paths, repository or branch names,
policy contents (in the ping), environment values, provider keys,
host names or user names. The ping contains none of them by
construction; the report contains only what the bundle shows you.

## Your controls

`codereview telemetry status | enable | disable`. `disable` deletes
the install id. `CODEREVIEW_TELEMETRY=0` overrides everything. At
most one ping per kind of crash per day.

## Retention and deletion

Data received through the feedback features above is kept for
90 days and no longer: access is limited to the project
maintainers, and anything older than 90 days is automatically
deleted (purged). To ask what we hold, or to have yours deleted
sooner, contact support@phpatch.com. A bundle you attach to a
public issue yourself stays in that issue until you or we
remove it — ask and we will.

## Contact

support@phpatch.com
