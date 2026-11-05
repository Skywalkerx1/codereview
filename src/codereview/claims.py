#!/usr/bin/env python3
"""Builder-claim verification for the run record — Epic C4.

A builder's work report asserts things: "I ran the tests and
they passed." The panel cannot run anything, so until now those
assertions entered a verification round as the builder's word.
This module checks the checkable part of them — the commands
the report claims were run, with the outcomes it claims they
had — and records the result in the run record's
`claim_verification` section.

The machinery is the Epic C evidence runner's, composed, never
duplicated: `evidence.parse_claims` is the one parser of claim
forms (a backtick-quoted command with an outcome on the same
line, or a labelled `Ran:` / `Tests:` / `Command:` line), and
`evidence.verify_claims` re-runs each claim through the C5
sandbox (throwaway copy of the tree, allow-listed environment,
no network, timeouts, process-group kill). There is no second
parser and no second executor in this module; what it adds is
the record-facing contract around them:

- **Statuses.** Each extracted claim ends `verified` (the
  re-run matches the claim), `mismatch` (the re-run contradicts
  the claim — the claim is downgraded: recorded as not
  standing, with claimed vs actual outcomes stated), or
  `unverifiable` (the re-run could not be performed — the
  sandbox itself failed). A line that is *shaped* like a claim
  — it presents a command in backticks, or carries a claim
  label — but does not parse to an unambiguous command +
  outcome is recorded as `unparsed`: never guessed at, never
  executed. Ordinary prose is not a claim attempt and is not
  recorded at all.
- **Boundary, stated plainly.** Claim verification is evidence
  recorded in the run record. It is NOT a gate input: no claim
  status changes the verdict, a finding, or any other gate
  input, and nothing in the gate reads this section. A mismatch
  downgrades the *claim*, never the gate — the gate consumes
  configured evidence through the C3 rule (`evidence.
  gate_effect`) and the panel's findings, exactly as before.
  The section's own `boundary` field repeats this in every
  record that carries it.
- **Never raises.** A malformed report, a missing tree, a
  sandbox failure — every failure is a recorded outcome
  (`unverifiable`, with the reason), never an exception. A
  run whose builder report cannot be claim-checked still
  produces its record.

The standalone surface predates this module and keeps its own
vocabulary (`codereview evidence --claims report.md`, statuses
confirmed / downgraded / error); the mapping to this section's
vocabulary happens here, in one place.
"""

from __future__ import annotations

from . import evidence as _evidence
from .core import redact_secrets

SCHEMA = "codereview.claims/1"

BOUNDARY = (
    "Claim verification is evidence recorded in the run "
    "record. It is not a gate input: no claim status changes "
    "the verdict, a finding, or any other gate input. A "
    "mismatch downgrades the claim, never the gate.")

# The evidence runner's statuses, in this section's vocabulary.
_STATUS_MAP = {"confirmed": "verified", "downgraded": "mismatch",
               "error": "unverifiable"}

STATUSES = ("verified", "mismatch", "unverifiable", "unparsed")

_UNPARSED_TEXT_CHARS = 200


def _unparsed_entries(text, parsed_lines):
    """Claim-shaped lines the parser did not extract, as
    `unparsed` entries. A line is claim-shaped when it presents
    a command in a backtick span or carries one of the claim
    labels — the two forms `evidence.parse_claims` recognises.
    The span form is checked first, mirroring the parser's own
    precedence. Everything else is prose, not a claim attempt,
    and is left unrecorded."""
    entries = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if lineno in parsed_lines:
            continue
        if _evidence._SPAN_RE.search(line):
            reason = ("command presented without an unambiguous "
                      "claimed outcome — not extracted, not run")
        elif _evidence._CLAIM_LABEL_RE.match(line):
            reason = ("labelled line did not yield an "
                      "unambiguous command and outcome — not "
                      "extracted, not run")
        else:
            continue
        entries.append({
            "line": lineno,
            "status": "unparsed",
            "text": redact_secrets(line.strip())[
                :_UNPARSED_TEXT_CHARS],
            "reason": reason})
    return entries


def verify_report_claims(report_text, source_dir, timeout=None,
                         environ=None):
    """Verify a builder work report's claimed commands against
    `source_dir` and return the run record's
    `claim_verification` section — or None when there is no
    report to check (None / empty / whitespace-only), so a run
    without a builder report carries no section at all.

    Never raises. `timeout` is per claimed command and defaults
    to the evidence runner's own bound — one timeout discipline
    for every command the sandbox executes (C5)."""
    if report_text is None:
        return None
    if isinstance(report_text, bytes):
        report_text = report_text.decode("utf-8", "replace")
    if not isinstance(report_text, str):
        return {"schema": SCHEMA, "boundary": BOUNDARY,
                "claims": [],
                "summary": {"total": 0, "verified": 0,
                            "mismatch": 0, "unverifiable": 0,
                            "unparsed": 0},
                "detail": "builder report was not text "
                          f"({type(report_text).__name__}); "
                          "no claims could be checked"}
    if not report_text.strip():
        return None
    if timeout is None:
        timeout = _evidence.DEFAULT_TIMEOUT
    try:
        parsed = _evidence.parse_claims(report_text)
    except Exception:  # noqa: BLE001 — recorded below, not raised
        parsed = []
    entries = []
    try:
        result = _evidence.verify_claims(
            report_text, source_dir, timeout=timeout,
            environ=environ)
        for claim in result.get("claims") or []:
            entries.append({
                "line": claim.get("line"),
                "command": claim.get("command"),
                "claimed": claim.get("claimed"),
                "claimed_exit_code": claim.get(
                    "claimed_exit_code"),
                "status": _STATUS_MAP.get(claim.get("status"),
                                          "unverifiable"),
                "actual_exit_code": claim.get("actual_exit_code"),
                "duration_s": claim.get("duration_s"),
                "output_sha256": claim.get("output_sha256"),
                "detail": claim.get("detail") or ""})
    except Exception as exc:  # noqa: BLE001 — a verification that
        # could not run at all leaves every extracted claim
        # unverifiable, with the reason, and the run continues.
        for claim in parsed:
            entries.append({
                "line": claim.get("line"),
                "command": claim.get("command"),
                "claimed": claim.get("claimed"),
                "claimed_exit_code": claim.get(
                    "claimed_exit_code"),
                "status": "unverifiable",
                "actual_exit_code": None,
                "duration_s": None,
                "output_sha256": None,
                "detail": f"claim verification could not run: "
                          f"{exc}"})
    parsed_lines = {c.get("line") for c in parsed}
    entries.extend(_unparsed_entries(report_text, parsed_lines))
    entries.sort(key=lambda e: e.get("line") or 0)
    summary = {"total": len(entries)}
    for status in STATUSES:
        summary[status] = sum(1 for e in entries
                              if e["status"] == status)
    return {"schema": SCHEMA, "boundary": BOUNDARY,
            "claims": entries, "summary": summary}
