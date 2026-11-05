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
_TABLES = ("panel", "evidence", "gate", "paths", "waivers")


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
