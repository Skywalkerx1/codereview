#!/usr/bin/env python3
"""codereview seat-state supervision (Epic K2).

Every seat in a run carries a live state:

    pending -> working -> done | blocked:<class> | failed | timed-out

with blocked classes quota, auth, input, stalled. The state is
(a) emitted live through a progress callback (the CLI prints it),
and (b) persisted into the run record per seat (`seat_state` on
each reviewer report), next to the existing error_detail
machinery. A blocked seat is a failed job: it degrades the panel
through the ordinary reviewer-failure path — never silently
skipped, never a silent PASS.

Detection is OURS, over the seat subprocess's own signals —
exit code, captured stdout/stderr, output activity, timeout.
The failure-text table below is per-CLI and probe-grounded
(Epic K spec, U6 probe matrix, 2026-11-05): every pattern cites
the evidence it was taken from, and a CLI with no verified text
for a condition gets NO pattern for it — the seat then relies on
process signals alone. Herdr pane state is never an input here
(K3a territory: seats are not herdr-hosted yet, so there is no
pane to read; when hosting lands, pane state may be recorded as
an advisory annotation, never as the basis of a classification).

Vocabulary notes:

  * A `blocked:stalled` EPISODE (no output growth for
    STALL_AFTER_S) is a liveness signal, not a failure: a seat
    that prints only its final answer (Claude Code's -p mode)
    is silent while it thinks. The episode is recorded in the
    transitions and the seat returns to `working` if output
    resumes; `blocked:stalled` becomes the TERMINAL state only
    when the run's timeout kills a seat that has been silent
    past the bound.
  * `blocked:input` exists in the vocabulary with its detection
    path wired (a verified prompt pattern matched on stderr
    while the process waits) but has NO patterns today: no
    U6 probe produced verified interactive-prompt text for any
    of the three CLIs, and patterns are never invented.
  * Patterns are matched against stderr while the seat runs
    (stderr is the CLI's diagnostics channel — never the verdict
    channel) and, once the process has exited non-zero, against
    stderr then stdout (Claude Code prints in-run failures as
    the result on stdout; a successful run's stdout is never
    scanned, so a verdict quoting failure text from the diff
    under review cannot misclassify its own seat).
  * Matching is ANCHORED to the CLI's own voice (Phase 4,
    P4-06): a pattern counts only when, on its line, the text
    before the match is an unquoted lead-in — timestamps, a log
    level, a logger path, the vendor's own lead-ins ("You've",
    "HTTP error:") — never quoted matter. The verbatim vendor
    messages carry such lead-ins, so position-0 matching would
    reject the very evidence the table ships on; what the
    anchor rejects is the core appearing inside quotes: a
    warning about a named component ("MCP server 'docs' not
    logged in") states the COMPONENT's state, not the CLI's,
    and verdict or diff text quoting the words is content
    under review. An unanchored substring match killed a
    healthy seat on exactly that warning.
"""

from __future__ import annotations

import contextvars
import os
import re
import threading
import time

STATES = ("pending", "working", "blocked", "done", "failed",
          "timed-out")
BLOCKED_CLASSES = ("quota", "auth", "input", "stalled")

# Live-supervision bounds (seconds). STALL_AFTER_S is the
# no-output bound for a stalled episode / a stalled terminal at
# timeout; BLOCK_GRACE_S is how long a matched blocked pattern
# must be followed by total output silence before the seat is
# terminated early (the CLI's own retry bursts keep output
# growing, so a genuinely stuck seat is what reaches the grace).
STALL_AFTER_S = 180.0
BLOCK_GRACE_S = 10.0

# ----------------------------------------------------------------
# U6 failure-pattern table. Provenance classes:
#   VERIFIED-LIVE   observed from the real binary on this VM
#   VERIFIED-DOCS   verbatim from the vendor's official docs
#   VERIFIED-SOURCE verbatim from the vendor's own source tree
# Patterns match on an apostrophe-free core where the vendor
# text uses a curly apostrophe (U+2019), so either rendering
# matches. Matching is case-insensitive throughout.
# ----------------------------------------------------------------
FAILURE_PATTERNS = {
    "claude": (
        # VERIFIED-DOCS: code.claude.com/docs/en/errors, "Usage
        # limits" — 'You've hit your session limit' / 'weekly' /
        # 'Opus' / 'Sonnet' / 'individual usage limit' variants.
        {"id": "claude-quota-limit", "class": "quota",
         "pattern": r"hit your (session|weekly|opus|sonnet|"
                    r"individual usage) limit"},
        # VERIFIED-DOCS: same page — 'spend limit reached'.
        {"id": "claude-quota-spend-limit", "class": "quota",
         "pattern": r"spend limit reached"},
        # VERIFIED-DOCS: same page — 'Credit balance is too low'.
        {"id": "claude-quota-credit-balance", "class": "quota",
         "pattern": r"credit balance is too low"},
        # VERIFIED-DOCS: same page, "Authentication" —
        # 'Not logged in · Please run /login'.
        {"id": "claude-auth-not-logged-in", "class": "auth",
         "pattern": r"not logged in"},
        # VERIFIED-DOCS: same page — 'Invalid API key'.
        {"id": "claude-auth-invalid-api-key", "class": "auth",
         "pattern": r"invalid api key"},
        # VERIFIED-DOCS: same page — 'API Error: 401 Invalid
        # authentication credentials'.
        {"id": "claude-auth-invalid-credentials", "class": "auth",
         "pattern": r"invalid authentication credentials"},
        # VERIFIED-DOCS: same page — 'Login expired · Please
        # run /login' and 'Claude.ai login expired'.
        {"id": "claude-auth-login-expired", "class": "auth",
         "pattern": r"login expired"},
    ),
    "codex": (
        # VERIFIED-SOURCE: openai/codex, codex-rs/protocol/src/
        # error.rs — every UsageLimitReached message begins
        # "You've hit your usage limit" (curly apostrophe in the
        # source; the pattern is the apostrophe-free core).
        {"id": "codex-quota-usage-limit", "class": "quota",
         "pattern": r"hit your usage limit"},
        # VERIFIED-SOURCE: same file — 'Quota exceeded. Check
        # your plan and billing details.' (QuotaExceeded).
        {"id": "codex-quota-exceeded", "class": "quota",
         "pattern": r"quota exceeded\. check your plan and "
                    r"billing details"},
        # VERIFIED-LIVE: codex-cli 0.164.0-alpha.9 on this VM,
        # logged out (2026-11-05): stderr carried 'HTTP error:
        # 401 Unauthorized' and 'unexpected status 401
        # Unauthorized: Missing bearer <redacted> ...' before
        # exiting 1 with stdout empty.
        {"id": "codex-auth-401", "class": "auth",
         "pattern": r"401 unauthorized"},
        {"id": "codex-auth-missing-bearer", "class": "auth",
         "pattern": r"missing bearer"},
    ),
    "gemini": (
        # VERIFIED-DOCS: geminicli.com/docs/resources/faq quotes
        # the failure verbatim: 'API error: 429 - Resource
        # exhausted' (RESOURCE_EXHAUSTED). Gemini's unauthen-
        # ticated-headless failure text is UNVERIFIED in the
        # official docs, so gemini carries no auth pattern.
        {"id": "gemini-quota-resource-exhausted", "class": "quota",
         "pattern": r"resource_exhausted|resource exhausted"},
    ),
}

_COMPILED = {
    cli: tuple({**p, "rx": re.compile(p["pattern"], re.IGNORECASE)}
               for p in patterns)
    for cli, patterns in FAILURE_PATTERNS.items()
}


def cli_key_for_argv(argv):
    """The pattern-table key for a seat command line: the
    basename of argv[0] when it names a tabled CLI, else None
    (a wrapper script, an unknown CLI — process signals only)."""
    if not argv:
        return None
    base = os.path.basename(str(argv[0]))
    if base.endswith(".exe"):
        base = base[:-4]
    return base if base in _COMPILED else None


_QUOTE_CHARS = ('"', "“", "”", "`")


def _unquoted_lead_in(prefix):
    """True when `prefix` (the line text before a match) states
    no quoted matter: no quote characters, and every apostrophe
    word-internal (You've — the vendor's own voice), never a
    quote opening or closing a span ('docs', "…")."""
    for i, ch in enumerate(prefix):
        if ch in _QUOTE_CHARS:
            return False
        if ch in ("'", "’"):
            left = prefix[i - 1] if i else ""
            right = prefix[i + 1] if i + 1 < len(prefix) else ""
            if not (left.isalpha() and right.isalpha()):
                return False
    return True


def match_failure(cli_key, text):
    """First tabled pattern matching `text` for `cli_key`, as
    {class, pattern, matched} — or None. Unknown CLI or no
    match both mean: no textual classification, by design.

    A match counts only under the P4-06 anchor: scanning line
    by line, the text before the match on its line must be an
    unquoted lead-in (see the module docstring). Pattern
    priority is the table's, exactly as when the whole text was
    searched at once."""
    if not cli_key or not text:
        return None
    lines = text.splitlines()
    for entry in _COMPILED.get(cli_key, ()):
        rx = entry["rx"]
        for line in lines:
            for m in rx.finditer(line):
                if _unquoted_lead_in(line[:m.start()]):
                    return {"class": entry["class"],
                            "pattern": entry["id"],
                            "matched": m.group(0)[:80]}
    return None


def classify_exit(cli_key, returncode, stdout_text, stderr_text):
    """Terminal classification for an exited seat process.

    Returns (state, class, evidence). A tabled pattern on
    stderr (then stdout — Claude's failure-as-result channel)
    classifies blocked:<class>; anything else is a plain
    failure with the exit code as evidence."""
    for source, text in (("stderr", stderr_text),
                         ("stdout", stdout_text)):
        hit = match_failure(cli_key, text or "")
        if hit:
            return "blocked", hit["class"], {
                "exit_code": returncode,
                "pattern": hit["pattern"],
                "matched": hit["matched"],
                "source": source}
    return "failed", "error", {"exit_code": returncode}


class SeatStateLog:
    """One job's state trace: the transitions list IS both the
    live stream (each emit fires `on_event`) and the record's
    `transitions` (spec §4.3 agreement rule — the record can
    never claim less than what was shown live, because both
    read this object). Thread-safe: a seat's runner thread
    emits while the job owner reads the summary."""

    def __init__(self, on_event=None):
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._transitions = []
        self._terminal = None
        self.on_event = on_event

    def _at_ms(self):
        return int((time.monotonic() - self._t0) * 1000)

    def emit(self, state, cls=None, evidence=None, terminal=False):
        tr = {"state": state, "class": cls, "at_ms": self._at_ms()}
        if evidence:
            tr["evidence"] = dict(evidence)
        if terminal:
            tr["terminal"] = True
        with self._lock:
            self._transitions.append(tr)
            if terminal:
                self._terminal = tr
        if self.on_event is not None:
            try:
                self.on_event(dict(tr))
            except Exception:  # noqa: BLE001 — a broken progress
                pass            # sink never breaks a review job
        return tr

    def summary(self):
        """The record form: terminal state/class/evidence plus
        the full transition trace."""
        with self._lock:
            transitions = [dict(t) for t in self._transitions]
            term = self._terminal or (
                transitions[-1] if transitions else
                {"state": "pending", "class": None})
        return {"state": term["state"],
                "class": term.get("class"),
                "evidence": dict(term.get("evidence") or {}),
                "transitions": transitions}


# The job currently executing on this thread/context, if any.
# core._review_job installs its log here for the duration of the
# job; providers.command_agent reads it to report live episodes
# (stalls) and attaches its terminal classification to the
# ProviderError it raises (`seat_facts`), which the job owner
# turns into the terminal transition. ContextVar so concurrent
# jobs on pooled threads never share a log.
CURRENT = contextvars.ContextVar(
    "codereview_seat_state_log", default=None)


def current_log():
    return CURRENT.get()
