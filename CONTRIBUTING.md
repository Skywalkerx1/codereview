# Reporting a problem

## If something goes wrong

1. Run `codereview --version`.
2. Re-run the failing command. Runs write a record (`.json` and
   `.md`) in the output directory (`codereview-out` by default).
3. Run `codereview support-bundle` and **read the zip** before you
   send it. It holds redacted configuration, the latest record and
   any crash note. Records contain excerpts of the code you
   reviewed; use `--no-records` to leave them out. Nothing is sent
   automatically.
4. Open an issue using a template and attach the bundle. Or run
   `codereview report`, which shows you what it would send and sends
   only after you confirm.
5. Security problems: do not file an issue; follow `SECURITY.md`.

## Exit codes are a contract

`0` pass, `1` blocked, `2` inconclusive **or an internal error**.
A crash prints one line (`codereview: internal error (...)`) and
exits 2, and writes a redacted `codereview-crash-*.json` note.
`--debug` (or `CODEREVIEW_DEBUG=1`) also prints the redacted
traceback. A crash is always a bug; please report it.

## Severity

S0 security, secret exposure, data loss, wrong gate outcome. S1
documented behaviour broken, silent degradation, hang, crash. S2
minor. S3 note. Say which you think it is; we may re-rate.

## What to attach

Version, command line (redact anything private), the support bundle,
and for a false positive or false negative the finding and why it is
wrong.

## Anonymous crash ping (optional, off by default)

`codereview telemetry enable` turns on a minimal anonymous ping on
crashes. See `PRIVACY.md` for exactly what it sends.
