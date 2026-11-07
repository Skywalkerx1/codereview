"""Verdict record schema v1.0.0 — the one versioned record contract.

Every surface (CLI, MCP server, GitHub adapter, agent seats,
workflow/loop driver) calls the same core (`core.run_review` /
`core.run_verification`) and therefore emits the same record.
This module is that record's formal contract:

- `RECORD_SCHEMA` — a JSON-Schema-style definition (a plain
  dict; the product is stdlib-only, so no external schema
  library is involved) describing what the core ACTUALLY emits.
- `validate_record(record)` — the in-tree validator. The core
  validates every record at emission (`finalize_record` raises
  on a violation), and `core.write_report` re-validates a v1
  record before it is written to disk, so a record that reaches
  disk — the copy the MCP `get_verdict` tool reads back — is a
  record that validated.
- `finalize_record(report, ...)` — the core's last step before
  a report is returned: it stamps the v1 sections below onto
  the legacy record shape and validates the result. It never
  touches the gate, the findings, or any verdict logic — this
  is record-shape work only.

Relationship to the legacy tag: records have always carried
`schema: "codereview.report/1"`. That tag is KEPT (consumers
compare it literally) and v1.0.0 is carried alongside it as
`schema_version`. A record with the tag but no
`schema_version` is a legacy (pre-v1) record: readers must not
treat it as corrupt, but it makes no v1 promises — in
particular its verify-mode records may lack `coverage` and
`degraded_causes`, and no record of that era carries `checks`,
`panel`, `cost`, or `record_identity` sections.

Semantics locked by this schema (the GTM engineering contract):

- Verdicts are PASS / BLOCKED / INCONCLUSIVE. The record's
  legacy `gate` field spells them lowercase ("pass" /
  "blocked" / "inconclusive"); the v1 `verdict` field carries
  the uppercase spelling, and the two must agree. CLI exit
  codes are 0 (PASS), 1 (BLOCKED), 2 (INCONCLUSIVE) — see
  `EXIT_CODES`.
- A PASS means: no actionable issue was found under the
  checks that ran. It is NOT a correctness guarantee. The
  record states this in its `verdict_semantics` section.
- Checks that did not run must be visible: the `checks`
  section lists `run`, `not_run`, and `unavailable` (attempted
  but produced no result — e.g. every reviewer seat errored)
  separately. A PASS over a partial check set is visible as
  such, never dressed up as a full one.
- Degraded-provider behaviour is explicit: `degraded` +
  `degraded_causes` on the record, per-seat status/family/tier
  in `panel.seats`, and a degraded panel can never be read as
  a healthy one (see core's gate rules, unchanged by this
  schema).
- Cost: the core has NO cost data — providers return review
  text only and report no usage to the core. The v1 record
  says so explicitly (`cost.status == "not_available"`)
  instead of omitting the field or inventing a number. (The
  bench wrapper estimates cost per attempt from its own seat
  price config, outside this record, under the separate
  `codereview.benchresult/1` schema.)
- Record identity/path: `record_identity.id` is a content
  hash stamped at emission. The record's PATH is assigned by
  the writer, not the core, so at emission `record_identity
  .path` is null; `core.write_report` stamps the file's base
  name into the written copy, and the MCP payload carries the
  full path as `record_path`, outside the record.
- Record content integrity (P6-03): the writer also stamps
  `record_identity.content_sha256` — a hash over the WHOLE
  record except the `record_identity` envelope itself (the
  id is a hash of a subset; the path is location metadata,
  so a renamed file still verifies). record-verify
  recomputes it in single and chain mode: ANY later edit —
  a finding's status, the gate, forged test results — fails
  verification. Threat model, stated plainly: this detects
  edits and corruption by anything that does not recompute
  the hash (hand edits, torn copies, accidental mutation).
  It is NOT a signature: an editor who recomputes the hash
  over their edited record passes. Records written before
  the hash existed carry none and verify under the legacy
  rule — the check reports not-applicable, exactly like the
  coverage/tier/sidecar checks treat their pre-machinery
  records — because registered and pilot records are
  evidence and must not become unverifiable retroactively.
  The legacy rule is bounded by provenance (P6-12): it
  applies only when the record's own declarations
  establish that it predates the stamp (see
  `content_hash_required`). The first bound trusted
  whatever a single edited field declared, and read
  missing or unparseable fields as pre-stamp — deleting
  or garbling two fields reopened the downgrade (Phase 6
  rerun 2). The rule now fails closed: EVERY declaration
  (the top-level version, `provenance.generator_version`,
  `created_at`) is read; a stamping-era or unparseable
  declaration defeats the exemption, and no usable
  declarations at all defeats it — legacy requires
  positive, consistent, pre-stamp evidence. What remains
  is the stated limit above: recompute the hash, or
  rewrite every declaration into one consistent pre-stamp
  claim — the hash was never a signature. One documented
  cost: unstamped records written by 0.13.0 dev builds in
  the hours before the stamp landed (stamping-era version
  line, pre-stamp `created_at`) no longer read as legacy;
  that window's artefacts are dev records, not registered
  evidence — the B2-era records predate the 0.13.0 version
  line entirely and keep the exemption. Records with no
  trace of the v1 machinery at all (no `schema_version`,
  `provenance` or `record_identity`) are read by the same
  rule on their surviving declarations (P6-12b, rerun 3):
  the three-key deletion from a current record no longer
  reaches a categorical exemption — a surviving
  stamping-era `version` defeats it, and no declarations
  at all establishes nothing. Genuine pre-schema records
  carry a pre-stamp `version` and `created_at` and keep
  the exemption on that evidence.
"""

import datetime
import hashlib
import json
import re

SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "codereview.report/1"

# The verdict vocabulary. `gate` keeps the historical lowercase
# spelling; `verdict` is the same fact in the contract's
# uppercase spelling.
GATES = ("pass", "blocked", "inconclusive")
VERDICTS = ("PASS", "BLOCKED", "INCONCLUSIVE")
VERDICT_FOR_GATE = dict(zip(GATES, VERDICTS))
EXIT_CODES = {"pass": 0, "blocked": 1, "inconclusive": 2}

MODES = ("review", "verify")
SEVERITIES = ("blocker", "major", "minor", "nit")
EVIDENCE_CLASSES = ("E0", "E1", "E2", "E3")

PASS_MEANS = ("no actionable issue found under the checks "
              "that ran (see the checks section)")
PASS_IS_NOT = ("not a correctness guarantee: checks that did "
               "not run are listed in checks.not_run / "
               "checks.unavailable, and a degraded panel is "
               "labelled in panel / degraded_causes")

# JSON-Schema-style definition of the v1 record. It describes
# the emitted shape: `required` is the v1 core contract, and
# `additionalProperties` is deliberately true — the record has
# always grown optional, mode- and feature-specific sections
# (policy, tiering, evidence, disputes, hooks, ...) and a v1
# reader must tolerate sections it does not know.
RECORD_SCHEMA = {
    "$id": "codereview.report/1",
    "version": SCHEMA_VERSION,
    "title": "CodeReview verdict record",
    "type": "object",
    "additionalProperties": True,
    "required": [
        "schema", "schema_version", "version", "mode",
        "created_at", "gate", "verdict", "gate_reasons",
        "findings", "reviewer_reports", "degraded",
        "degraded_causes", "truncated", "scope", "checks",
        "panel", "cost", "duration_ms", "waivers",
        "provenance", "record_identity", "verdict_semantics",
    ],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "schema_version": {"const": SCHEMA_VERSION},
        "version": {"type": "string",
                    "description": "product version that "
                                   "produced the record"},
        "mode": {"enum": list(MODES)},
        "created_at": {"type": "string",
                       "description": "ISO-8601 creation time"},
        "gate": {"enum": list(GATES),
                 "description": "legacy lowercase verdict"},
        "verdict": {"enum": list(VERDICTS),
                    "description": "uppercase verdict; must "
                                   "agree with gate"},
        "gate_reasons": {"type": "array",
                         "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "description": "merged findings standing at the "
                           "gate (review mode); in verify mode, "
                           "NEW findings raised by the round — "
                           "prior blockers live in cleared / "
                           "remaining / unjudged",
            "items": {
                "type": "object",
                "required": ["id", "severity", "title"],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"enum": list(SEVERITIES)},
                    "category": {"type": ["string", "null"]},
                    "file": {"type": ["string", "null"]},
                    "line": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "evidence": {"type": ["string", "null"]},
                    "evidence_quote": {
                        "type": ["string", "null"]},
                    "evidence_class": {
                        "enum": list(EVIDENCE_CLASSES),
                        "description": "E0 deterministic, E2 "
                                       "probe-confirmed, E1 "
                                       "corroborated, E3 "
                                       "single-source / "
                                       "uncorroborated. Absent "
                                       "means unstamped (legacy "
                                       "or deterministic-era "
                                       "finding), never E0."},
                    "recommendation": {
                        "type": ["string", "null"]},
                    "confidence": {
                        "type": ["number", "null"]},
                },
            },
        },
        "reviewer_reports": {
            "type": "array",
            "description": "one entry per reviewer job that "
                           "ran (per seat/lens/batch in review "
                           "mode; per seat in verify mode)",
            "items": {
                "type": "object",
                "required": ["provider", "status"],
                "properties": {
                    "provider": {"type": ["string", "null"]},
                    "lens": {"type": ["string", "null"]},
                    "status": {"enum": ["ok", "error"]},
                    "family": {"type": ["string", "null"]},
                    "tier": {"type": ["string", "null"]},
                    "duration_ms": {
                        "type": ["integer", "null"]},
                },
            },
        },
        "degraded": {"type": "boolean"},
        "degraded_causes": {"type": "array",
                            "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
        "patch_sha256": {"type": "string",
                         "description": "sha256 of the patch "
                                        "text reviewed"},
        "scope": {
            "type": "object",
            "required": ["files", "patch_sha256"],
            "properties": {
                "files": {"type": "array",
                          "items": {"type": "string"}},
                "patch_sha256": {"type": "string"},
                "patch_chars": {"type": ["integer", "null"]},
                "range": {"type": ["string", "null"],
                          "description": "git range, when the "
                                         "caller recorded one "
                                         "(CLI runs); null for "
                                         "direct core callers"},
                "head": {"type": ["string", "null"],
                         "description": "commit the range was "
                                        "taken at, same "
                                        "provenance as range"},
                "previous_gate": {"type": ["string", "null"],
                                  "description": "verify mode: "
                                                 "the prior "
                                                 "record's gate"},
            },
        },
        "checks": {
            "type": "object",
            "required": ["run", "not_run", "unavailable"],
            "description": "check availability, explicit: a "
                           "check is in exactly one list. "
                           "Names: deterministic_scan, "
                           "reviewer_panel, tests, evidence, "
                           "policy, coverage (review mode "
                           "only; verify mode lists coverage "
                           "as not_run — a known, documented "
                           "gap: the verification round does "
                           "not recompute per-file coverage)",
            "properties": {
                "run": {"type": "array",
                        "items": {"type": "string"}},
                "not_run": {"type": "array",
                            "items": {"type": "string"}},
                "unavailable": {"type": "array",
                                "items": {"type": "string"}},
            },
        },
        "panel": {
            "type": "object",
            "required": ["seats", "degraded", "degraded_causes"],
            "properties": {
                "seats": {
                    "type": "array",
                    "description": "distinct seats by "
                                   "(provider, lens), first "
                                   "report wins for status",
                    "items": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": ["string", "null"]},
                            "lens": {
                                "type": ["string", "null"]},
                            "family": {
                                "type": ["string", "null"]},
                            "tier": {
                                "type": ["string", "null"]},
                            "status": {
                                "type": ["string", "null"]},
                        },
                    },
                },
                "families": {"type": "array",
                             "items": {"type": "string"}},
                "seat_count": {"type": "integer"},
                "ok_count": {"type": "integer"},
                "degraded": {"type": "boolean"},
                "degraded_causes": {"type": "array",
                                    "items": {"type": "string"}},
            },
        },
        "cost": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"const": "not_available"},
                "amount_usd": {"type": "null"},
                "reason": {"type": "string"},
            },
        },
        "duration_ms": {"type": ["integer", "null"],
                        "description": "core wall-clock for "
                                       "the round; null only "
                                       "when timing was not "
                                       "recorded"},
        "waivers": {
            "type": "array",
            "description": "waivers the caller recorded for "
                           "this round (review mode: the "
                           "policy-evaluation waivers, verbatim;"
                           " verify mode: always empty — "
                           "verification waivers live in the "
                           "loop/workflow state, documented "
                           "gap, not hidden)",
            "items": {"type": "object"},
        },
        "provenance": {
            "type": "object",
            "required": ["generator", "generator_version",
                         "patch_sha256"],
            "properties": {
                "generator": {"const": "codereview"},
                "generator_version": {"type": "string"},
                "patch_sha256": {"type": "string"},
                "range": {"type": ["string", "null"]},
                "head": {"type": ["string", "null"]},
            },
        },
        "record_identity": {
            "type": "object",
            "required": ["id", "path"],
            "properties": {
                "id": {"type": "string",
                       "description": "sha256 over mode + "
                                      "created_at + patch hash "
                                      "+ gate, computed at "
                                      "emission"},
                "path": {"type": ["string", "null"],
                         "description": "null at emission; "
                                        "write_report stamps "
                                        "the written file's "
                                        "base name"},
                "content_sha256": {
                    "type": "string",
                    "description": "P6-03: sha256 over the "
                                   "whole record except the "
                                   "record_identity envelope, "
                                   "stamped by write_report; "
                                   "record-verify recomputes "
                                   "it. Detects edits, is not "
                                   "a signature. Absent on "
                                   "records written before it "
                                   "existed (legacy)"},
            },
        },
        "verdict_semantics": {
            "type": "object",
            "required": ["pass_means", "pass_is_not"],
            "properties": {
                "pass_means": {"const": PASS_MEANS},
                "pass_is_not": {"const": PASS_IS_NOT},
            },
        },
    },
}


def _check_names(report):
    """Derive the checks section from the finished report.

    Every name lands in exactly one list. A reviewer panel that
    was configured but whose every job errored is `unavailable`
    (attempted, no result) — not `run`, and not silently
    absent. No panel at all is `not_run`."""
    mode = report.get("mode")
    run, not_run, unavailable = [], [], []

    def place(name, bucket):
        bucket.append(name)

    # Deterministic scan: run_review always scans; the
    # verification round re-checks prior deterministic findings
    # against the new scan by construction.
    place("deterministic_scan", run)
    reports = report.get("reviewer_reports") or []
    if not reports:
        place("reviewer_panel", not_run)
    elif any(r.get("status") == "ok" for r in reports
             if isinstance(r, dict)):
        place("reviewer_panel", run)
    else:
        place("reviewer_panel", unavailable)
    place("tests", run if report.get("test_results") else not_run)
    if mode == "review":
        place("evidence", run if report.get("evidence") is not None
              else not_run)
        place("policy", run if report.get("policy") is not None
              else not_run)
        place("coverage", run if report.get("coverage") is not None
              else not_run)
    else:  # verify
        # The verify round collects no evidence record, evaluates
        # no policy, and recomputes no coverage — visible here,
        # not papered over (see RECORD_SCHEMA.checks).
        for name in ("evidence", "policy", "coverage"):
            place(name, not_run)
    return {"run": run, "not_run": not_run,
            "unavailable": unavailable}


def _panel_section(report):
    seats, seen = [], set()
    for rep in report.get("reviewer_reports") or []:
        if not isinstance(rep, dict):
            continue
        key = (rep.get("provider"), rep.get("lens"))
        if key in seen:
            continue
        seen.add(key)
        seats.append({
            "provider": rep.get("provider"),
            "lens": rep.get("lens"),
            "family": rep.get("family"),
            "tier": rep.get("tier"),
            "status": rep.get("status"),
        })
    # Canonical order: reviewer_reports arrive in completion
    # order (a thread artifact); the panel section is a summary
    # of composition, so it sorts by (provider, lens) and two
    # records of equivalent runs carry identical panel sections.
    seats.sort(key=lambda s: (str(s["provider"]),
                              str(s["lens"])))
    families = sorted({s["family"] for s in seats
                       if s["family"] not in (None, "", "unknown")})
    return {
        "seats": seats,
        "families": families,
        "seat_count": len(seats),
        "ok_count": sum(1 for s in seats if s["status"] == "ok"),
        "degraded": bool(report.get("degraded")),
        "degraded_causes": list(report.get("degraded_causes") or []),
    }


def record_content_sha256(record):
    """The P6-03 content hash: sha256 of the record's
    canonical JSON (sorted keys, compact separators) with the
    `record_identity` envelope excluded. Excluding the whole
    envelope is what lets the writer stamp the hash INTO the
    envelope without self-reference, and keeps the hash a
    statement about the record's content rather than its
    file name."""
    body = {k: v for k, v in record.items()
            if k != "record_identity"}
    canon = json.dumps(body, ensure_ascii=False,
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# The stamping era (P6-12): the first generator line whose
# writer stamps content_sha256 on every record it writes,
# and the moment that stamp landed (the P6-03 commit,
# 2026-11-07T02:07:56Z). The two bounds classify each of a
# record's provenance declarations as pre-stamp or
# stamping-era; `content_hash_required` reads them all
# and fails closed (see its docstring for the rule and
# the rerun-2 history).
CONTENT_HASH_ERA_VERSION = (0, 13, 0)
CONTENT_HASH_ERA_FROM = datetime.datetime(
    2026, 11, 7, 2, 7, 56, tzinfo=datetime.timezone.utc)

_VERSION_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _version_tuple(text):
    """The leading numeric dotted prefix of a version
    string as a tuple ("0.13.0.dev0" → (0, 13, 0)), or
    None when the string carries no numeric prefix."""
    if not isinstance(text, str):
        return None
    match = _VERSION_PREFIX_RE.match(text)
    if not match:
        return None
    return tuple(int(p) for p in match.group(1).split("."))


def _created_instant(text):
    """A record's created_at as an aware datetime, or None
    when it does not parse (a naive value is read as UTC —
    that is the only form the writer emits)."""
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(
            text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _version_state(value):
    """A version declaration classified: "absent" (None),
    "garbled" (present but carries no numeric prefix),
    "pre" (predates the stamping-era version line) or
    "era" (the stamping-era line or later)."""
    if value is None:
        return "absent"
    parsed = _version_tuple(value)
    if parsed is None:
        return "garbled"
    return ("era" if parsed >= CONTENT_HASH_ERA_VERSION
            else "pre")


def _created_state(value):
    """A created_at declaration classified like
    `_version_state`, against the stamp instant."""
    if value is None:
        return "absent"
    parsed = _created_instant(value)
    if parsed is None:
        return "garbled"
    return ("era" if parsed >= CONTENT_HASH_ERA_FROM
            else "pre")


def content_hash_required(record):
    """True when a record carrying no
    `record_identity.content_sha256` must NOT take the
    legacy exemption — the hash was removed, or the claim
    to have never been stamped does not hold up (P6-12).

    The record's THREE provenance declarations are read:
    the top-level `version`, `provenance.generator_version`
    and `created_at`. Legacy is a positive-evidence rule
    and fails closed:

    - any declaration in the stamping era defeats it (a
      single edited field cannot outvote the others);
    - any declaration present but unparseable defeats it
      (garbled provenance is not pre-stamp provenance);
    - no usable declarations on a record of the
      declarations era defeats it (absent provenance is
      not pre-stamp provenance);
    - legacy requires at least one parseable pre-stamp
      declaration and no defeating one.

    The rule applies inside the pre-machinery shape too
    (P6-12b, rerun 3): a record carrying no trace of the
    v1 machinery (no `schema_version`, no `provenance`,
    no `record_identity`) is NOT categorically exempt —
    its surviving declarations (`version`, `created_at`)
    are read by the same rule. That closes the three-key
    deletion: dropping the machinery sections from a
    current record while keeping `version: 0.13.0.dev0`
    (her G6) declares the stamping era and fails, and
    deleting every declaration (her G1) establishes
    nothing and fails. Genuine pre-schema records still
    pass: every writer of that era stamped `version` and
    `created_at` (the 0.9.4 / 0.9.6 historicals carry
    both), so one parseable pre-stamp declaration is
    positive evidence, not a new burden. A record with
    no declarations at all was never written by any
    version of the writer; the consistent-forgery
    residual (forge every declaration pre-stamp, her
    G2/G3/G4) remains the documented not-a-signature
    limit, unchanged.

    The first P6-12 bound read missing/unparseable fields
    as pre-stamp and let any one edited declaration carry
    the claim, so stripping the hash plus deleting or
    garbling two fields reopened the downgrade (Phase 6
    rerun 2, p6_downgrade2.py). Documented cost of failing
    closed: unstamped records from 0.13.0 dev builds in
    the hours before the stamp landed (stamping-era
    version line, pre-stamp `created_at`) no longer read
    as legacy — a closed set of dev artefacts; registered
    and B2-era records predate the 0.13.0 line entirely.
    """
    provenance = record.get("provenance")
    generator_version = (provenance.get("generator_version")
                         if isinstance(provenance, dict)
                         else None)
    states = [
        _version_state(record.get("version")),
        _version_state(generator_version),
        _created_state(record.get("created_at")),
    ]
    if "era" in states or "garbled" in states:
        return True
    return "pre" not in states


def _record_id(report):
    material = json.dumps({
        "mode": report.get("mode"),
        "created_at": report.get("created_at"),
        "patch_sha256": report.get("patch_sha256"),
        "gate": report.get("gate"),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def finalize_record(report, duration_ms=None, waivers=None):
    """Stamp the v1.0.0 sections onto a finished core report
    and validate it. Called by core.run_review /
    core.run_verification as their last step (before verdict
    notifications, which read only gate/findings). Raises
    ValueError listing every problem when the finished record
    does not meet the schema — an emission bug must fail loud,
    never write a record that claims v1 and is not.

    Idempotent in identity: a record that already carries a
    record_identity.id keeps it (the CLI's hooks rewrite goes
    through write_report, not back through here, but a caller
    re-finalising a record must not mint a second identity)."""
    gate = report.get("gate")
    files = report.get("files")
    if files is None:
        # Verify mode carries no file list; the scope is the
        # files of the patch it judged, which the caller of
        # finalize cannot see — core passes them via the
        # report's `_scope_files` scratch key when it has them.
        files = report.pop("_scope_files", None) or []
    else:
        report.pop("_scope_files", None)
    report["schema_version"] = SCHEMA_VERSION
    report["verdict"] = VERDICT_FOR_GATE.get(gate)
    report["scope"] = {
        "files": list(files),
        "patch_sha256": report.get("patch_sha256"),
        "patch_chars": report.get("patch_chars"),
        "range": report.get("range"),
        "head": report.get("head"),
        "previous_gate": report.get("previous_gate"),
    }
    report["checks"] = _check_names(report)
    report["panel"] = _panel_section(report)
    report["cost"] = {
        "status": "not_available",
        "amount_usd": None,
        "currency": "USD",
        "reason": ("core providers return review text only and "
                   "report no usage/cost to the core; bench "
                   "wrappers may estimate cost outside this "
                   "record (codereview.benchresult/1 cost_usd)"),
    }
    report["duration_ms"] = duration_ms
    normalised = []
    for waiver in waivers or []:
        normalised.append(waiver if isinstance(waiver, dict)
                          else {"finding_id": str(waiver)})
    report["waivers"] = normalised
    report["provenance"] = {
        "generator": "codereview",
        "generator_version": report.get("version"),
        "patch_sha256": report.get("patch_sha256"),
        "range": report.get("range"),
        "head": report.get("head"),
    }
    existing = report.get("record_identity") or {}
    report["record_identity"] = {
        "id": existing.get("id") or _record_id(report),
        "path": existing.get("path"),
    }
    report["verdict_semantics"] = {
        "pass_means": PASS_MEANS,
        "pass_is_not": PASS_IS_NOT,
    }
    problems = validate_record(report)
    if problems:
        raise ValueError(
            "verdict record failed schema v" + SCHEMA_VERSION
            + " validation at emission: " + "; ".join(problems))
    return report


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_record(record):
    """Validate a record against RECORD_SCHEMA (v1.0.0).

    Returns a list of problem strings — empty means valid.
    This is a hand-rolled validator for the subset of
    JSON-Schema the definition uses (types, required, enum,
    const), stdlib only. It validates the v1 contract, not
    every optional section the record may carry: unknown
    sections are permitted (additionalProperties) and their
    own sub-schemas (evidence, tiering, precedents, ...) keep
    their own validators."""
    problems = []

    def bad(msg):
        problems.append(msg)

    if not isinstance(record, dict):
        return ["record is not an object"]
    if record.get("schema") != SCHEMA_ID:
        bad(f"schema is {record.get('schema')!r}, "
            f"expected {SCHEMA_ID!r}")
    if record.get("schema_version") != SCHEMA_VERSION:
        bad(f"schema_version is {record.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION!r} (a record without it is "
            f"a legacy pre-v1 record, not a v1 record)")
    if not isinstance(record.get("version"), str) \
            or not record.get("version"):
        bad("version must be a non-empty string")
    mode = record.get("mode")
    if mode not in MODES:
        bad(f"mode is {mode!r}, expected one of {MODES} "
            f"(the loop summary record is a container of verdict "
            f"records, not itself a v1 verdict record)")
    if not isinstance(record.get("created_at"), str) \
            or not record.get("created_at"):
        bad("created_at must be a non-empty string")
    gate = record.get("gate")
    if gate not in GATES:
        bad(f"gate is {gate!r}, expected one of {GATES}")
    elif record.get("verdict") != VERDICT_FOR_GATE[gate]:
        bad(f"verdict is {record.get('verdict')!r} but gate "
            f"{gate!r} requires {VERDICT_FOR_GATE[gate]!r}")
    reasons = record.get("gate_reasons")
    if not isinstance(reasons, list) \
            or not all(isinstance(r, str) for r in reasons or []):
        bad("gate_reasons must be a list of strings")
    if not isinstance(record.get("degraded"), bool):
        bad("degraded must be a boolean")
    causes = record.get("degraded_causes")
    if not isinstance(causes, list) \
            or not all(isinstance(c, str) for c in causes or []):
        bad("degraded_causes must be a list of strings "
            "(verify-mode records before v1 omitted it; v1 "
            "requires it, empty when not degraded)")
    if record.get("degraded") and isinstance(causes, list) \
            and not causes:
        bad("degraded is true but degraded_causes is empty: "
            "degraded behaviour must name its cause(s)")
    if not isinstance(record.get("truncated"), bool):
        bad("truncated must be a boolean")
    findings = record.get("findings")
    if not isinstance(findings, list):
        bad("findings must be a list")
    else:
        for i, finding in enumerate(findings):
            if not isinstance(finding, dict):
                bad(f"findings[{i}] is not an object")
                continue
            if not finding.get("id"):
                bad(f"findings[{i}] has no id")
            if finding.get("severity") not in SEVERITIES:
                bad(f"findings[{i}] severity is "
                    f"{finding.get('severity')!r}, expected one "
                    f"of {SEVERITIES}")
            if not isinstance(finding.get("title"), str):
                bad(f"findings[{i}] title must be a string")
            eclass = finding.get("evidence_class")
            if eclass is not None and eclass not in EVIDENCE_CLASSES:
                bad(f"findings[{i}] evidence_class is "
                    f"{eclass!r}, expected one of "
                    f"{EVIDENCE_CLASSES} or absent (unstamped)")
    reports = record.get("reviewer_reports")
    if not isinstance(reports, list):
        bad("reviewer_reports must be a list")
    else:
        for i, rep in enumerate(reports):
            if not isinstance(rep, dict):
                bad(f"reviewer_reports[{i}] is not an object")
                continue
            if "provider" not in rep:
                bad(f"reviewer_reports[{i}] has no provider")
            if rep.get("status") not in ("ok", "error"):
                bad(f"reviewer_reports[{i}] status is "
                    f"{rep.get('status')!r}, expected 'ok' or "
                    f"'error'")
    scope = record.get("scope")
    if not isinstance(scope, dict):
        bad("scope must be an object")
    else:
        if not isinstance(scope.get("files"), list):
            bad("scope.files must be a list")
        if scope.get("patch_sha256") != record.get("patch_sha256"):
            bad("scope.patch_sha256 does not match the record's "
                "patch_sha256")
    if not (isinstance(record.get("patch_sha256"), str)
            and len(record.get("patch_sha256") or "") == 64):
        bad("patch_sha256 must be a 64-char sha256 hex string")
    checks = record.get("checks")
    if not isinstance(checks, dict):
        bad("checks must be an object")
    else:
        lists = {}
        for key in ("run", "not_run", "unavailable"):
            value = checks.get(key)
            if not isinstance(value, list) \
                    or not all(isinstance(c, str) for c in value or []):
                bad(f"checks.{key} must be a list of check names")
            lists[key] = set(value or [])
        seen = lists["run"] | lists["not_run"] | lists["unavailable"]
        total = sum(len(lists[k]) for k in lists)
        if len(seen) != total:
            bad("checks lists overlap: every check must be in "
                "exactly one of run / not_run / unavailable")
        if mode == "review" and gate == "pass" \
                and "reviewer_panel" in lists.get("unavailable", set()):
            bad("gate is pass but checks.unavailable contains "
                "reviewer_panel: a PASS may not rest on a panel "
                "that produced no result")
    panel = record.get("panel")
    if not isinstance(panel, dict):
        bad("panel must be an object")
    else:
        if not isinstance(panel.get("seats"), list):
            bad("panel.seats must be a list")
        if panel.get("degraded") != record.get("degraded"):
            bad("panel.degraded does not match the record's "
                "degraded flag")
    cost = record.get("cost")
    if not isinstance(cost, dict) \
            or cost.get("status") != "not_available":
        bad("cost must be an object with status "
            "'not_available' (the core has no cost data; a "
            "record claiming a core cost figure is inventing "
            "one)")
    elif cost.get("amount_usd") is not None:
        bad("cost.amount_usd must be null when cost.status is "
            "not_available")
    duration = record.get("duration_ms")
    if duration is not None and not _is_int(duration):
        bad("duration_ms must be an integer or null")
    waivers = record.get("waivers")
    if not isinstance(waivers, list) \
            or not all(isinstance(w, dict) for w in waivers or []):
        bad("waivers must be a list of waiver records (objects)")
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        bad("provenance must be an object")
    else:
        if provenance.get("generator") != "codereview":
            bad("provenance.generator must be 'codereview'")
        if provenance.get("patch_sha256") \
                != record.get("patch_sha256"):
            bad("provenance.patch_sha256 does not match the "
                "record's patch_sha256")
    identity = record.get("record_identity")
    if not isinstance(identity, dict):
        bad("record_identity must be an object")
    else:
        if not (isinstance(identity.get("id"), str)
                and len(identity.get("id") or "") == 64):
            bad("record_identity.id must be a 64-char sha256 "
                "hex string")
        if identity.get("path") is not None \
                and not isinstance(identity.get("path"), str):
            bad("record_identity.path must be a string or null")
        chash = identity.get("content_sha256")
        if chash is not None and not (
                isinstance(chash, str) and len(chash) == 64
                and all(c in "0123456789abcdef"
                        for c in chash)):
            bad("record_identity.content_sha256 must be a "
                "64-char sha256 hex string when present")
    semantics = record.get("verdict_semantics")
    if not isinstance(semantics, dict) \
            or semantics.get("pass_means") != PASS_MEANS \
            or semantics.get("pass_is_not") != PASS_IS_NOT:
        bad("verdict_semantics must carry the locked "
            "pass_means / pass_is_not wording")
    return problems
