#!/usr/bin/env python3
"""codereview project policy — the `.codereview.toml` file
(Epic B of the adopted roadmap).

A project policy is the REPOSITORY's own review contract: the
panel a change must face, the evidence it must carry, the extra
rules for sensitive paths, and the terms on which findings may
be waived. It is a different thing from the per-user setup
(`userconfig.py`): the setup says which models a PERSON runs;
the policy says what a PROJECT requires of any review, whoever
runs it. The gate (core.run_review) reads the policy and the
record lists every rule that applied and every violation found;
a blocking violation turns a PASS into BLOCKED. Nothing here
chooses models — policy constrains the panel's shape (size,
vendor families, lens coverage), never its members.

File: `.codereview.toml` at the repository root (the review
command discovers it there; `--policy PATH` overrides).
Parsed with stdlib `tomllib` only. An invalid file fails with a
line-referenced error and stops the run — a broken policy is
loud, never silently ignored.

Schema (every key optional; defaults in parentheses):

  [panel]
  min_seats = 0            # successful seats required (0 = none)
  min_families = 0         # distinct known vendor families among
                           # successful seats (0 = none)
  required_families = []   # families that must serve successfully,
                           # e.g. ["google", "openai"]
  require_lenses = []      # lenses needing a successful seat;
                           # subset of ["correctness", "operations"]

  [evidence]
  require_tests = false        # a test command must have run
  require_tests_pass = false   # ... and every test must have passed

  [gate]
  profile = "strict"       # the gate profile: "strict" (the
                           # default — every blocking-severity
                           # finding blocks) or "balanced"
                           # (policy B1, step 6: a blocking
                           # finding whose merged sources are
                           # solely the operations lens, with
                           # no correctness-lens or
                           # deterministic corroboration within
                           # the gate's merge identity, is
                           # demoted to a visible minor). The
                           # CLI's --gate-profile overrides
                           # this; the default stays "strict"
                           # until Baseline v2 confirms B1 on
                           # the holdout. A third profile from
                           # the original design, "quiet"
                           # (blanket corroboration for every
                           # lens), was REJECTED on the step-4
                           # replay evidence — it demoted three
                           # real single-seat majors — and is
                           # not implemented: its absence is a
                           # decision, not an omission, and
                           # naming it here is an error.

  [[paths]]                # repeatable; applies when the change
  match = "auth/**"        # touches a path matching this pattern
  require_full_panel = false   # every configured seat must serve
  require_tests = false
  require_tests_pass = false
  min_seats = 0
  min_families = 0
  enforce = "block"            # "block" | "advisory" (advisory
                               # violations are recorded, never
                               # gate-changing)

  [waivers]
  allow = true             # false: any recorded waiver violates
  require_reason = false   # a waiver without a reason violates
  max_age_days = 0         # >0: a waiver older than this (or with
                           # no usable date) is expired

  [diversity]              # Epic E3 panel-diversity
  min_families = 0         # enforcement, judged on the
                           # COMPOSED panel before any seat is
                           # called (distinct from [panel]
                           # min_families, which judges the
                           # seats that SERVED): the panel must
                           # span at least this many distinct
                           # known vendor families (0 = check
                           # off unless exclusion is enabled)
  exclude_builder_family = false
                           # true: when the run's caller knows
                           # the builder's vendor family, seats of
                           # that family are excluded from the
                           # panel when the remaining panel still
                           # meets min_families (or, with no
                           # minimum, still leaves a seat); when
                           # exclusion would breach the minimum
                           # the seats stay and the record says
                           # why. No caller knowing the family ⇒
                           # the exclusion never engages.
  enforce = "degrade"      # what a diversity violation does:
                           # "degrade" (the default) labels the
                           # run degraded and records the
                           # violation as advisory — never
                           # gate-changing; "block" additionally
                           # makes it a blocking policy violation

  [hooks]                  # Epic L3 lifecycle hooks: shell
  pre_run = ""             # commands fired around the run —
                           # pre_run before any seat call,
  post_verdict = ""        # post_verdict after the record is
                           # written, and
  on_blocked = ""          # on_blocked (also after the record
                           # is written) when the run's first
                           # seat ended in a K2 blocked class.
  timeout = 600            # per-hook wall-clock bound, seconds
                           # Hooks run through the Epic C
                           # evidence sandbox and are pure
                           # notification: their results land in
                           # the record's `hooks` section and
                           # they can NEVER change a verdict, a
                           # finding, or any gate input (see
                           # hooks.py). An empty/absent command
                           # means the event does not fire.

  [risk]                   # Epic E1 risk scorer: when
  enabled = false          # enabled, every review run's
                           # record gains a `risk` section —
                           # the deterministic score, band, and
                           # reasons computed by risk.py from
                           # the change's paths, size, touched
                           # sensitive patterns, and dependency
                           # changes. Descriptive only in E1:
                           # the score never changes a verdict
                           # (tiering/escalation consume it in
                           # E2/E4). Disabled (the default)
                           # leaves records byte-identical.
  medium_threshold = 35    # score >= this is band "medium"
  high_threshold = 70      # score >= this is band "high";
                           # each threshold is 0..100 and
                           # medium must be below high.
  tiering = false          # Epic E2/E4 tiered panels: when
                           # true (and enabled is true), the
                           # band sizes the panel — low runs
                           # the pre-screen seat(s) only,
                           # medium a reduced panel, high the
                           # full panel with evidence
                           # required — and a reduced panel
                           # that returns a blocking finding,
                           # a reviewer failure, or an
                           # unserved lens escalates to the
                           # full panel within the run (see
                           # tiering.py). Off (the default)
                           # leaves runs byte-identical.
  prescreen_seats = []     # seat names for the low tier;
                           # empty = the composed panel's
                           # first seat.
  medium_seats = []        # seat names for the medium tier;
                           # empty = the first tasked seat
                           # per lens.

With no policy file, the effective policy is the defaults
above: no requirements at all. CodeReview ships no imposed
project policy, exactly as it ships no default panel.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import tomllib

POLICY_FILENAME = ".codereview.toml"
POLICY_SCHEMA = "codereview.policy/1"

# Mirrors core.LENSES (the two review lenses). Kept here so this
# module stays import-free of the engine; a test pins the two
# together so they cannot drift.
KNOWN_LENSES = ("correctness", "operations")

# Mirrors core.GATE_PROFILES (the gate profiles, step 6), kept
# here under the same import-free discipline; a test pins the
# two together.
KNOWN_GATE_PROFILES = ("strict", "balanced")

_ENFORCE_LEVELS = ("block", "advisory")

_PANEL_KEYS = ("min_seats", "min_families", "required_families",
               "require_lenses")
_EVIDENCE_KEYS = ("require_tests", "require_tests_pass")
_GATE_KEYS = ("profile",)
_PATH_KEYS = ("match", "require_full_panel", "require_tests",
              "require_tests_pass", "min_seats", "min_families",
              "enforce")
_WAIVER_KEYS = ("allow", "require_reason", "max_age_days")
_HOOK_KEYS = ("pre_run", "post_verdict", "on_blocked", "timeout")
_HOOK_COMMAND_KEYS = ("pre_run", "post_verdict", "on_blocked")
_RISK_KEYS = ("enabled", "medium_threshold", "high_threshold",
              "tiering", "prescreen_seats", "medium_seats")
# Mirror risk.DEFAULT_MEDIUM_THRESHOLD /
# risk.DEFAULT_HIGH_THRESHOLD (Epic E1), kept here under the
# same import-free discipline as KNOWN_LENSES; a test pins the
# pairs together so they cannot drift.
_RISK_DEFAULT_MEDIUM_THRESHOLD = 35
_RISK_DEFAULT_HIGH_THRESHOLD = 70
_DIVERSITY_KEYS = ("min_families", "exclude_builder_family",
                   "enforce")
_DIVERSITY_ENFORCE_LEVELS = ("degrade", "block")
_TABLES = ("panel", "evidence", "gate", "paths", "waivers",
           "hooks", "risk", "diversity")


class PolicyError(ValueError):
    """A policy file that cannot be parsed or validated. The
    message names the file and, whenever it can be located, the
    line of the offending key."""


def default_policy():
    """The effective policy when no file exists: no requirements."""
    return {
        "schema": POLICY_SCHEMA,
        "path": None,
        "sha256": None,
        "panel": {"min_seats": 0, "min_families": 0,
                  "required_families": [], "require_lenses": []},
        "evidence": {"require_tests": False,
                     "require_tests_pass": False},
        "gate": {"profile": "strict"},
        "paths": [],
        "waivers": {"allow": True, "require_reason": False,
                    "max_age_days": 0},
        "hooks": {"pre_run": None, "post_verdict": None,
                  "on_blocked": None, "timeout": None},
        "risk": {"enabled": False, "medium_threshold": None,
                 "high_threshold": None, "tiering": False,
                 "prescreen_seats": [], "medium_seats": []},
        "diversity": {"min_families": 0,
                      "exclude_builder_family": False,
                      "enforce": "degrade"},
    }


def find_policy(repo="."):
    """The discovered policy path for a repo, or None."""
    candidate = os.path.join(repo or ".", POLICY_FILENAME)
    return candidate if os.path.exists(candidate) else None


# ----------------------------------------------------------------
# Loading + validation (B1). Errors are line-referenced: TOML
# syntax errors carry tomllib's own line; semantic errors locate
# the offending key by scanning the source lines for its table
# header and assignment (the locator only serves error messages,
# so an exotic formatting it cannot follow falls back to the
# table's line, then to the file as a whole).

def _locate(lines, table, key=None, occurrence=0):
    """1-based line of `key` under the `occurrence`-th `[table]`
    (or `[[table]]`) header, else the header's own line, else
    None."""
    header_line = None
    current = None
    seen = -1
    header_re = re.compile(r"\[\[?\s*([^\]\s]+)\s*\]\]?")
    for i, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if stripped.startswith("["):
            m = header_re.match(stripped)
            current = m.group(1) if m else None
            if current == table:
                seen += 1
                if seen == occurrence:
                    header_line = i
                    if key is None:
                        return i
            continue
        if current == table and seen == occurrence and key:
            if re.match(re.escape(key) + r"\s*=", stripped):
                return i
    return header_line


def _fail(source, lines, message, table=None, key=None,
          occurrence=0):
    line = _locate(lines, table, key, occurrence) if table else None
    where = f"{source}:{line}" if line else str(source)
    raise PolicyError(f"{where}: {message}")


def _check_int(value, source, lines, table, key, occurrence=0):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(source, lines,
              f"[{table}] {key} must be an integer, got "
              f"{type(value).__name__}", table, key, occurrence)
    if value < 0:
        _fail(source, lines,
              f"[{table}] {key} must be >= 0, got {value}",
              table, key, occurrence)
    return value


def _check_bool(value, source, lines, table, key, occurrence=0):
    if not isinstance(value, bool):
        _fail(source, lines,
              f"[{table}] {key} must be true or false, got "
              f"{type(value).__name__}", table, key, occurrence)
    return value


def _check_str_list(value, source, lines, table, key,
                    occurrence=0):
    if not isinstance(value, list) or any(
            not isinstance(v, str) or not v.strip()
            for v in value):
        _fail(source, lines,
              f"[{table}] {key} must be a list of non-empty "
              f"strings", table, key, occurrence)
    return [str(v) for v in value]


def _check_keys(table_data, allowed, source, lines, table,
                occurrence=0):
    if not isinstance(table_data, dict):
        _fail(source, lines, f"[{table}] must be a TOML table",
              table, occurrence=occurrence)
    for key in table_data:
        if key not in allowed:
            _fail(source, lines,
                  f"unknown key {key!r} in [{table}] (allowed: "
                  f"{', '.join(allowed)})", table, key, occurrence)


def load_policy(path):
    """Load + validate a policy file -> the effective policy
    dict (defaults filled, source path + content hash recorded).
    Raises PolicyError on any problem."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyError(f"{path}: not valid UTF-8 ({exc})")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"{path}: invalid TOML: {exc}")
    lines = text.splitlines()
    for key in data:
        if key not in _TABLES:
            line = None
            for i, raw_line in enumerate(lines, 1):
                if raw_line.strip().startswith(f"[{key}]") \
                        or raw_line.strip().startswith(f"[[{key}]]") \
                        or re.match(re.escape(key) + r"\s*=",
                                    raw_line.strip()):
                    line = i
                    break
            where = f"{path}:{line}" if line else str(path)
            raise PolicyError(
                f"{where}: unknown top-level key/table {key!r} "
                f"(policy tables are: {', '.join(_TABLES)}; bare "
                f"keys must live inside one of them)")

    policy = default_policy()
    policy["path"] = str(path)
    policy["sha256"] = hashlib.sha256(raw).hexdigest()

    panel = data.get("panel") or {}
    _check_keys(panel, _PANEL_KEYS, path, lines, "panel")
    if "min_seats" in panel:
        policy["panel"]["min_seats"] = _check_int(
            panel["min_seats"], path, lines, "panel", "min_seats")
    if "min_families" in panel:
        policy["panel"]["min_families"] = _check_int(
            panel["min_families"], path, lines, "panel",
            "min_families")
    if "required_families" in panel:
        policy["panel"]["required_families"] = _check_str_list(
            panel["required_families"], path, lines, "panel",
            "required_families")
    if "require_lenses" in panel:
        lenses = _check_str_list(
            panel["require_lenses"], path, lines, "panel",
            "require_lenses")
        for lens in lenses:
            if lens not in KNOWN_LENSES:
                _fail(path, lines,
                      f"[panel] require_lenses names unknown lens "
                      f"{lens!r} (known: {', '.join(KNOWN_LENSES)})",
                      "panel", "require_lenses")
        policy["panel"]["require_lenses"] = lenses

    evidence = data.get("evidence") or {}
    _check_keys(evidence, _EVIDENCE_KEYS, path, lines, "evidence")
    for key in _EVIDENCE_KEYS:
        if key in evidence:
            policy["evidence"][key] = _check_bool(
                evidence[key], path, lines, "evidence", key)

    gate = data.get("gate") or {}
    _check_keys(gate, _GATE_KEYS, path, lines, "gate")
    if "profile" in gate:
        if gate["profile"] not in KNOWN_GATE_PROFILES:
            _fail(path, lines,
                  f"[gate] profile must be one of "
                  f"{', '.join(KNOWN_GATE_PROFILES)}, got "
                  f"{gate['profile']!r} ('quiet' was considered "
                  f"and rejected on the step-4 replay evidence "
                  f"— it is not an implemented profile)",
                  "gate", "profile")
        policy["gate"]["profile"] = gate["profile"]

    raw_paths = data.get("paths") or []
    if not isinstance(raw_paths, list):
        _fail(path, lines,
              "[paths] must be an array of tables ([[paths]])",
              "paths")
    for idx, entry in enumerate(raw_paths):
        _check_keys(entry, _PATH_KEYS, path, lines, "paths", idx)
        match = entry.get("match")
        if not isinstance(match, str) or not match.strip():
            _fail(path, lines,
                  "[[paths]] entry needs a non-empty 'match' "
                  "pattern (e.g. \"auth/**\")", "paths", "match",
                  idx)
        rule = {"match": match,
                "require_full_panel": False,
                "require_tests": False,
                "require_tests_pass": False,
                "min_seats": 0, "min_families": 0,
                "enforce": "block"}
        for key in ("require_full_panel", "require_tests",
                    "require_tests_pass"):
            if key in entry:
                rule[key] = _check_bool(entry[key], path, lines,
                                        "paths", key, idx)
        for key in ("min_seats", "min_families"):
            if key in entry:
                rule[key] = _check_int(entry[key], path, lines,
                                       "paths", key, idx)
        if "enforce" in entry:
            if entry["enforce"] not in _ENFORCE_LEVELS:
                _fail(path, lines,
                      f"[[paths]] enforce must be one of "
                      f"{', '.join(_ENFORCE_LEVELS)}, got "
                      f"{entry['enforce']!r}", "paths", "enforce",
                      idx)
            rule["enforce"] = entry["enforce"]
        policy["paths"].append(rule)

    waivers = data.get("waivers") or {}
    _check_keys(waivers, _WAIVER_KEYS, path, lines, "waivers")
    for key in ("allow", "require_reason"):
        if key in waivers:
            policy["waivers"][key] = _check_bool(
                waivers[key], path, lines, "waivers", key)
    if "max_age_days" in waivers:
        policy["waivers"]["max_age_days"] = _check_int(
            waivers["max_age_days"], path, lines, "waivers",
            "max_age_days")

    hooks = data.get("hooks") or {}
    _check_keys(hooks, _HOOK_KEYS, path, lines, "hooks")
    for key in _HOOK_COMMAND_KEYS:
        if key in hooks:
            value = hooks[key]
            if not isinstance(value, str) or not value.strip():
                _fail(path, lines,
                      f"[hooks] {key} must be a non-empty "
                      f"command string, got {value!r}",
                      "hooks", key)
            policy["hooks"][key] = value
    if "timeout" in hooks:
        value = hooks["timeout"]
        if isinstance(value, bool) \
                or not isinstance(value, (int, float)) \
                or value <= 0:
            _fail(path, lines,
                  f"[hooks] timeout must be a positive number "
                  f"of seconds, got {value!r}", "hooks",
                  "timeout")
        policy["hooks"]["timeout"] = value

    risk = data.get("risk") or {}
    _check_keys(risk, _RISK_KEYS, path, lines, "risk")
    if "enabled" in risk:
        policy["risk"]["enabled"] = _check_bool(
            risk["enabled"], path, lines, "risk", "enabled")
    for key in ("medium_threshold", "high_threshold"):
        if key in risk:
            value = _check_int(risk[key], path, lines, "risk",
                               key)
            if value > 100:
                _fail(path, lines,
                      f"[risk] {key} must be at most 100, got "
                      f"{value}", "risk", key)
            policy["risk"][key] = value
    # The effective band pair (stored values over the module
    # defaults) must be ordered, whether or not scoring is
    # enabled — an inverted pair is a broken policy either way
    # and B1 errors are loud, never deferred to first use.
    _medium = policy["risk"]["medium_threshold"]
    if _medium is None:
        _medium = _RISK_DEFAULT_MEDIUM_THRESHOLD
    _high = policy["risk"]["high_threshold"]
    if _high is None:
        _high = _RISK_DEFAULT_HIGH_THRESHOLD
    if _medium >= _high:
        _fail(path, lines,
              f"[risk] medium_threshold ({_medium}) must be "
              f"below high_threshold ({_high}) — the bands "
              f"would be empty or inverted", "risk",
              "high_threshold")
    if "tiering" in risk:
        policy["risk"]["tiering"] = _check_bool(
            risk["tiering"], path, lines, "risk", "tiering")
    for key in ("prescreen_seats", "medium_seats"):
        if key in risk:
            policy["risk"][key] = _check_str_list(
                risk[key], path, lines, "risk", key)
    if policy["risk"]["tiering"] \
            and not policy["risk"]["enabled"]:
        # Tiering consumes the risk band; with the scorer
        # disabled there is no band to tier on, so the
        # combination is a broken policy — loud at load,
        # never a silent no-op at run time (B1).
        _fail(path, lines,
              "[risk] tiering = true requires enabled = true "
              "— tiering is driven by the risk score, and a "
              "disabled scorer produces no band", "risk",
              "tiering")
    diversity = data.get("diversity") or {}
    _check_keys(diversity, _DIVERSITY_KEYS, path, lines,
                "diversity")
    if "min_families" in diversity:
        policy["diversity"]["min_families"] = _check_int(
            diversity["min_families"], path, lines, "diversity",
            "min_families")
    if "exclude_builder_family" in diversity:
        policy["diversity"]["exclude_builder_family"] = \
            _check_bool(diversity["exclude_builder_family"],
                        path, lines, "diversity",
                        "exclude_builder_family")
    if "enforce" in diversity:
        if diversity["enforce"] not in _DIVERSITY_ENFORCE_LEVELS:
            _fail(path, lines,
                  f"[diversity] enforce must be one of "
                  f"{', '.join(_DIVERSITY_ENFORCE_LEVELS)}, got "
                  f"{diversity['enforce']!r}", "diversity",
                  "enforce")
        policy["diversity"]["enforce"] = diversity["enforce"]
    return policy


def render_effective(policy):
    """Deterministic text rendering of the effective policy —
    what `codereview policy check` prints (B3)."""
    def _b(value):
        return "true" if value else "false"

    def _lst(values):
        return "[" + ", ".join(f'"{v}"' for v in values) + "]"

    panel, evidence, waivers = (policy["panel"],
                                policy["evidence"],
                                policy["waivers"])
    gate = policy["gate"]
    lines = [
        "[panel]",
        f"min_seats = {panel['min_seats']}",
        f"min_families = {panel['min_families']}",
        f"required_families = {_lst(panel['required_families'])}",
        f"require_lenses = {_lst(panel['require_lenses'])}",
        "",
        "[evidence]",
        f"require_tests = {_b(evidence['require_tests'])}",
        f"require_tests_pass = {_b(evidence['require_tests_pass'])}",
        "",
        "[gate]",
        f"profile = \"{gate['profile']}\"",
        "",
    ]
    for rule in policy["paths"]:
        lines += [
            "[[paths]]",
            f"match = \"{rule['match']}\"",
            f"require_full_panel = {_b(rule['require_full_panel'])}",
            f"require_tests = {_b(rule['require_tests'])}",
            f"require_tests_pass = {_b(rule['require_tests_pass'])}",
            f"min_seats = {rule['min_seats']}",
            f"min_families = {rule['min_families']}",
            f"enforce = \"{rule['enforce']}\"",
            "",
        ]
    lines += [
        "[waivers]",
        f"allow = {_b(waivers['allow'])}",
        f"require_reason = {_b(waivers['require_reason'])}",
        f"max_age_days = {waivers['max_age_days']}",
    ]
    hooks = policy.get("hooks") or {}
    hook_lines = []
    for key in _HOOK_COMMAND_KEYS:
        if hooks.get(key):
            escaped = str(hooks[key]).replace("\\", "\\\\") \
                .replace('"', '\\"')
            hook_lines.append(f'{key} = "{escaped}"')
    if hooks.get("timeout") is not None:
        hook_lines.append(f"timeout = {hooks['timeout']}")
    if hook_lines:
        # Rendered only when a hook is actually configured, so
        # a hookless policy renders exactly as it did before
        # Epic L3.
        lines += ["", "[hooks]"] + hook_lines
    risk = policy.get("risk") or {}
    if risk.get("enabled"):
        # Rendered only when risk scoring is enabled, so a
        # riskless policy renders exactly as it did before
        # Epic E1 (same rule as [hooks] above).
        medium = risk.get("medium_threshold")
        if medium is None:
            medium = _RISK_DEFAULT_MEDIUM_THRESHOLD
        high = risk.get("high_threshold")
        if high is None:
            high = _RISK_DEFAULT_HIGH_THRESHOLD
        lines += ["", "[risk]", "enabled = true",
                  f"medium_threshold = {medium}",
                  f"high_threshold = {high}"]
        if risk.get("tiering"):
            # Rendered only when tiering is on, so a policy
            # without it renders exactly as it did before
            # Epic E2 (same rule as the [risk] block itself).
            lines += [
                "tiering = true",
                "prescreen_seats = "
                + _lst(risk.get("prescreen_seats") or []),
                "medium_seats = "
                + _lst(risk.get("medium_seats") or []),
            ]
    diversity = policy.get("diversity") or {}
    if diversity.get("min_families") \
            or diversity.get("exclude_builder_family") \
            or diversity.get("enforce") not in (None, "degrade"):
        # Rendered only when diversity enforcement is actually
        # configured, so a policy without it renders exactly as
        # it did before Epic E3.
        lines += [
            "",
            "[diversity]",
            f"min_families = {diversity.get('min_families') or 0}",
            "exclude_builder_family = "
            + _b(bool(diversity.get("exclude_builder_family"))),
            f"enforce = \"{diversity.get('enforce') or 'degrade'}\"",
        ]
    return "\n".join(lines)


# ----------------------------------------------------------------
# Evaluation (B2): the gate's view of a finished review round.
# Pure and deterministic: given the policy and the round's facts
# (changed files, reviewer reports, test results, recorded
# waivers), produce the rules that applied and the violations.
# `path_matches` is the engine's matcher (core.path_matches),
# passed in so path semantics live in exactly one place.

def _waiver_date(waiver):
    """The waiver's recorded date as a datetime.date, or None.
    Accepts 'date', 'waived_at', or 'created_at' (ISO date or
    datetime)."""
    for key in ("date", "waived_at", "created_at"):
        value = waiver.get(key)
        if not value:
            continue
        text = str(value).strip()
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            continue
    return None


def evaluate_policy(policy, *, files, reviewer_reports,
                    test_results, waivers=(), path_matches,
                    today=None):
    """-> {"applied": [...], "violations": [...]}.

    Each applied entry: {"rule", "requirement", "status"} with
    status "satisfied" or "violated". Each violation: {"rule",
    "detail", "enforce"} — "block" violations are gate-changing
    (the caller turns a PASS into BLOCKED); "advisory" ones are
    recorded only. A rule is 'applied' only when the policy
    actually configures it (non-default) and, for path rules,
    when the change touches a matching path."""
    applied, violations = [], []

    def check(rule, requirement, ok, detail, enforce="block"):
        applied.append({"rule": rule, "requirement": requirement,
                        "status": "satisfied" if ok else "violated"})
        if not ok:
            violations.append({"rule": rule, "detail": detail,
                               "enforce": enforce})

    reports = reviewer_reports or []
    ok_reports = [r for r in reports if r.get("status") == "ok"]
    ok_seats = sorted({r.get("provider") for r in ok_reports
                       if r.get("provider")})
    all_seats = sorted({r.get("provider") for r in reports
                        if r.get("provider")})
    families = sorted({r.get("family") for r in ok_reports
                       if r.get("family")
                       not in (None, "", "unknown")})
    lenses_ok = {r.get("lens") for r in ok_reports if r.get("lens")}
    tests = test_results or []
    tests_ran = len(tests) > 0
    tests_failed = [t for t in tests if not t.get("ok")]
    tests_ok = tests_ran and not tests_failed

    def tests_detail(verb):
        if not tests_ran:
            return f"policy requires {verb} but no test command ran"
        return (f"policy requires {verb} but "
                f"{len(tests_failed)} of {len(tests)} test "
                f"command(s) failed")

    panel = policy["panel"]
    if panel["min_seats"]:
        check("panel.min_seats",
              f"at least {panel['min_seats']} successful seat(s)",
              len(ok_seats) >= panel["min_seats"],
              f"policy requires at least {panel['min_seats']} "
              f"successful seat(s); {len(ok_seats)} served "
              f"({', '.join(ok_seats) or 'none'})")
    if panel["min_families"]:
        check("panel.min_families",
              f"at least {panel['min_families']} distinct vendor "
              f"families",
              len(families) >= panel["min_families"],
              f"policy requires at least {panel['min_families']} "
              f"distinct vendor families among successful seats; "
              f"saw {len(families)} ({', '.join(families) or 'none'})")
    for fam in panel["required_families"]:
        check("panel.required_families",
              f"family {fam!r} serves successfully",
              fam in families,
              f"policy requires vendor family {fam!r} on the "
              f"panel; it did not serve successfully (served: "
              f"{', '.join(families) or 'none'})")
    for lens in panel["require_lenses"]:
        check("panel.require_lenses",
              f"lens {lens!r} covered by a successful seat",
              lens in lenses_ok,
              f"policy requires a successful {lens!r} reviewer; "
              f"none served")

    evidence = policy["evidence"]
    if evidence["require_tests"]:
        check("evidence.require_tests",
              "test results recorded",
              tests_ran,
              "policy requires test evidence but no test command "
              "ran")
    if evidence["require_tests_pass"]:
        check("evidence.require_tests_pass",
              "all tests pass",
              tests_ok,
              tests_detail("passing tests"))

    changed = list(files or [])
    for rule in policy["paths"]:
        matched = [f for f in changed
                   if path_matches(f, [rule["match"]])]
        if not matched:
            continue
        scope = f"paths[{rule['match']}]"
        where = (f"change touches {len(matched)} path(s) matching "
                 f"{rule['match']!r}")
        enforce = rule["enforce"]
        if rule["require_full_panel"]:
            missing = [s for s in all_seats if s not in ok_seats]
            check(f"{scope}.require_full_panel",
                  "every configured seat serves successfully",
                  bool(all_seats) and not missing,
                  f"{where}: the full panel is required but "
                  f"seat(s) {', '.join(missing) or 'none configured'} "
                  f"did not serve successfully",
                  enforce)
        if rule["min_seats"]:
            check(f"{scope}.min_seats",
                  f"at least {rule['min_seats']} successful seat(s)",
                  len(ok_seats) >= rule["min_seats"],
                  f"{where}: at least {rule['min_seats']} "
                  f"successful seat(s) required; {len(ok_seats)} "
                  f"served", enforce)
        if rule["min_families"]:
            check(f"{scope}.min_families",
                  f"at least {rule['min_families']} distinct "
                  f"vendor families",
                  len(families) >= rule["min_families"],
                  f"{where}: at least {rule['min_families']} "
                  f"distinct vendor families required; saw "
                  f"{len(families)}", enforce)
        if rule["require_tests"]:
            check(f"{scope}.require_tests",
                  "test results recorded",
                  tests_ran,
                  f"{where}: test evidence is required but no "
                  f"test command ran", enforce)
        if rule["require_tests_pass"]:
            check(f"{scope}.require_tests_pass",
                  "all tests pass",
                  tests_ok,
                  f"{where}: " + tests_detail("passing tests"),
                  enforce)

    waiver_rules = policy["waivers"]
    waiver_list = list(waivers or [])
    if today is None:
        today = datetime.datetime.now(
            datetime.timezone.utc).date()
    for i, waiver in enumerate(waiver_list):
        if not isinstance(waiver, dict):
            violations.append({
                "rule": "waivers.shape",
                "detail": f"waiver #{i + 1} is not a record "
                          f"(a waiver must name its finding, "
                          f"reason, and date)",
                "enforce": "block"})
            continue
        fid = waiver.get("finding_id") or waiver.get("id") \
            or f"#{i + 1}"
        if not waiver_rules["allow"]:
            check("waivers.allow",
                  "no waivers recorded",
                  False,
                  f"policy does not permit waivers, but finding "
                  f"{fid} was waived")
        if waiver_rules["require_reason"]:
            check("waivers.require_reason",
                  f"waiver for {fid} records a reason",
                  bool(str(waiver.get("reason") or "").strip()),
                  f"waiver for finding {fid} records no reason; "
                  f"policy requires one")
        if waiver_rules["max_age_days"]:
            wdate = _waiver_date(waiver)
            if wdate is None:
                check("waivers.max_age_days",
                      f"waiver for {fid} is at most "
                      f"{waiver_rules['max_age_days']} day(s) old",
                      False,
                      f"waiver for finding {fid} carries no "
                      f"usable date; policy expires waivers after "
                      f"{waiver_rules['max_age_days']} day(s) and "
                      f"an undated waiver cannot prove freshness")
            else:
                age = (today - wdate).days
                check("waivers.max_age_days",
                      f"waiver for {fid} is at most "
                      f"{waiver_rules['max_age_days']} day(s) old",
                      age <= waiver_rules["max_age_days"],
                      f"waiver for finding {fid} is {age} day(s) "
                      f"old; policy expires waivers after "
                      f"{waiver_rules['max_age_days']} day(s)")

    return {"applied": applied, "violations": violations}
