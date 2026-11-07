#!/usr/bin/env python3
"""SARIF 2.1.0 export (Epic D, ticket D1).

`record_to_sarif(record)` converts a saved review record — the
dict `core.write_report` persists as JSON — into a SARIF 2.1.0
log (https://docs.oasis-open.org/sarif/sarif/v2.1.0/), the
interchange format GitHub code scanning and most other static
analysis surfaces ingest.

What is exported: every finding that is still OPEN on the
record, deduped by finding id — the merged `findings` list, a
verification record's still-open `remaining` list, and the
human-decision side lists (`disputed_findings`,
`refutation_weak_findings`, `escalated_findings`), whose
findings were partitioned out of `findings` by adjudication
routing but are not resolved: the gate stopped on them for a
human. Each result's properties carry its adjudication state.
Resolved or classified-away lists (cleared, withdrawn,
adjudicated-refuted, precedent-standing, fixture, archived,
out-of-scope) are NOT exported: code scanning should show
current open problems, not the record's full history.

Mapping (SARIF forces a few choices; each is deliberate):
- Rules derive from finding categories. A deterministic-scan
  finding keeps its scan rule id (`eval-exec`, ...) and takes
  its description and help text from the scan's own rule table;
  a model finding has no rule of its own in the record, so its
  rule id is `model-<category>` (`model-security`, ...).
- Severity maps blocker -> error, major -> warning,
  minor -> note, nit -> note. Every result carries its own
  level; a rule's defaultConfiguration level is the level of
  its most severe result.
- Locations come from the finding's file + line. A finding
  whose record entry carries a `line_basis` (which numbering
  the cited line uses — written by the dispute tooling) has
  that basis passed through in the result properties; SARIF
  regions have no basis field of their own. A finding with no
  file (a failing test command) gets no location: SARIF
  permits it, and inventing one would be a false claim.
- The region snippet is the finding's evidence quote (first
  line) — the exact text the reviewer cited.
- partialFingerprints carries the record's own finding id
  (`codereviewFindingId`), so alerts stay stable across runs
  exactly as far as the record's fingerprint is stable.
- The gate, mode, patch hash and other record facts ride in
  the run's property bag — SARIF's sanctioned extension point
  — never in fields a strict consumer could misread as its own.

The writer is stdlib-only, like the rest of the package.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import quote

from . import core

SARIF_SCHEMA_URL = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "master/Schemata/sarif-schema-2.1.0.json")
SARIF_VERSION = "2.1.0"

# Task-prescribed mapping; nit shares minor's level.
LEVEL_BY_SEVERITY = {"blocker": "error", "major": "warning",
                     "minor": "note", "nit": "note"}
_LEVEL_RANK = {"error": 0, "warning": 1, "note": 2, "none": 3}

# (record key, adjudication state) for the exported lists, in
# priority order: the first list a finding id appears in names
# its state. `findings`/`remaining` are the gate's standing set;
# the side lists are open items awaiting a human decision.
_EXPORT_LISTS = (("findings", "standing"),
                 ("remaining", "standing"),
                 ("disputed_findings", "disputed"),
                 ("refutation_weak_findings", "refutation-weak"),
                 ("escalated_findings", "escalated"))

# Canonical text for the deterministic rules, from the scan's
# own table: rule id -> (title, recommendation, category).
_DET_RULE_INFO = {rule_id: (title, rec, cat)
                  for rule_id, _sev, cat, _rx, title, rec
                  in core._RULES}


def level_for_severity(severity):
    """SARIF level for a record severity. Unknown severities
    take the path `_normalize_finding` takes: they behave as
    minor, hence note."""
    sev = str(severity or "minor").lower()
    return LEVEL_BY_SEVERITY.get(sev, LEVEL_BY_SEVERITY["minor"])


def record_findings(record):
    """The record's open findings, deduped by id, each paired
    with its adjudication state (see _EXPORT_LISTS)."""
    seen = set()
    out = []
    for key, state in _EXPORT_LISTS:
        for f in record.get(key) or []:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            out.append((f, state))
    return out


def _rule_id(finding):
    rule = str(finding.get("rule") or "").strip()
    if rule:
        return rule
    category = str(finding.get("category") or "correctness")
    return f"model-{category.lower()}"


def _rule_name(rule_id):
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", rule_id) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Rule"


def _build_rules(pairs):
    """One reportingDescriptor per rule id. The default level
    is the most severe level among the rule's results; every
    result still carries its own level explicitly."""
    by_id = {}
    for finding, _state in pairs:
        rid = _rule_id(finding)
        entry = by_id.setdefault(
            rid, {"finding": finding, "level": None})
        level = level_for_severity(finding.get("severity"))
        if entry["level"] is None \
                or _LEVEL_RANK[level] < _LEVEL_RANK[entry["level"]]:
            entry["level"] = level
    rules = []
    for rid in sorted(by_id):
        entry = by_id[rid]
        finding = entry["finding"]
        category = str(finding.get("category")
                       or "correctness").lower()
        canonical = _DET_RULE_INFO.get(rid)
        if canonical is not None:
            title, rec, _cat = canonical
            short = title
            full = (f"{title} — raised by CodeReview's "
                    f"deterministic scan (pattern match on the "
                    f"diff; no model involved).")
            help_text = rec
            kind = "deterministic"
        elif rid.startswith("model-"):
            short = f"Model-reported {category} finding"
            full = (f"A {category} problem reported by an "
                    f"independent reviewer model and carried "
                    f"through CodeReview's deterministic gate.")
            help_text = None
            kind = "model"
        else:
            # A scan rule the current table no longer carries
            # (an older record): describe it from the finding
            # itself rather than inventing canonical text.
            short = f"CodeReview deterministic check: {rid}"
            full = short + "."
            help_text = None
            kind = "deterministic"
        rule = {
            "id": rid,
            "name": _rule_name(rid),
            "shortDescription": {"text": short},
            "fullDescription": {"text": full},
            "defaultConfiguration": {"level": entry["level"]},
            "properties": {"category": category,
                           "tags": [category, kind]},
        }
        if help_text:
            rule["help"] = {"text": help_text}
        rules.append(rule)
    return rules


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_LINE = 2 ** 31 - 1


def _clean_message(text):
    """message.text with control characters stripped (P5-01):
    a finding title is model/diff-derived text and may carry
    raw newlines, NULs and other Cc characters that strict
    SARIF consumers reject."""
    return _CONTROL_CHARS.sub("", str(text))


def _artifact_uri(path):
    """Normalise a record file path to a SARIF artifactLocation
    uri (P5-01): a percent-encoded RELATIVE URI reference. Drive
    letters and leading slashes are stripped — the uri names a
    repo-relative artefact, and a hostile path must not be
    mistaken for a URI scheme.

    `..` segments are RESOLVED with posixpath.normpath, not
    dropped (P5-01b): dropping them silently repointed the
    finding (`a/../../b.py` became `a/b.py`, a different file).
    A path that still escapes the root after normalisation
    (a leading `../`) returns "" — the caller then emits no
    location rather than a pointer at the wrong file."""
    p = str(path or "").replace("\\", "/").strip()
    p = re.sub(r"^[A-Za-z]:", "", p)  # Windows drive letter
    p = p.lstrip("/")
    if not p:
        return ""
    p = posixpath.normpath(p)
    if p in (".", "..") or p.startswith("../"):
        return ""
    return "/".join(quote(s, safe="") for s in p.split("/"))


def _result(finding, state):
    rid = _rule_id(finding)
    severity = str(finding.get("severity") or "minor").lower()
    if severity not in core.SEVERITIES:
        severity = "minor"
    category = str(finding.get("category")
                   or "correctness").lower()
    result = {
        "ruleId": rid,
        "level": level_for_severity(severity),
        "message": {"text": _clean_message(finding.get("title")
                                           or "Untitled finding")},
        "partialFingerprints": {
            "codereviewFindingId": str(finding.get("id") or "")},
    }
    file = _artifact_uri(finding.get("file"))
    if file:
        physical = {"artifactLocation": {"uri": file}}
        region = {}
        line = finding.get("line")
        if isinstance(line, int) and not isinstance(line, bool) \
                and line >= 1:
            region["startLine"] = min(line, _MAX_LINE)
        quote = str(finding.get("evidence_quote") or "")
        if quote:
            region["snippet"] = {"text": quote.splitlines()[0][:500]}
        if region:
            physical["region"] = region
        result["locations"] = [{"physicalLocation": physical}]
    props = {
        "codereviewFindingId": str(finding.get("id") or ""),
        "severity": severity,
        "category": category,
        "adjudicationState": state,
        "sources": [str(s) for s in finding.get("sources") or []],
        "consensus": bool(finding.get("consensus")),
    }
    if finding.get("confidence") is not None:
        props["confidence"] = finding["confidence"]
    rec = str(finding.get("recommendation") or "")
    if rec:
        props["recommendation"] = rec
    # Optional record fields, passed through only when present:
    # grounding state, cross-family confirmation, and the line
    # basis the dispute tooling records (`line_basis` — which
    # numbering `line` uses, e.g. the head blob's).
    for src_key, prop_key in (("grounding", "grounding"),
                              ("cross_family", "crossFamily"),
                              ("line_basis", "lineBasis")):
        value = finding.get(src_key)
        if isinstance(value, str) and value:
            props[prop_key] = value
    result["properties"] = props
    return result


def record_to_sarif(record):
    """Convert a saved review record (dict) to a SARIF 2.1.0
    log (dict). Pure: no I/O, no mutation of the record."""
    pairs = record_findings(record)
    cr_props = {}
    for src_key, prop_key in (("schema", "recordSchema"),
                              ("mode", "mode"),
                              ("gate", "gate"),
                              ("created_at", "recordCreatedAt"),
                              ("patch_sha256", "patchSha256"),
                              ("range", "range"),
                              ("head", "head")):
        value = record.get(src_key)
        if value:
            cr_props[prop_key] = value
    reasons = [str(r) for r in record.get("gate_reasons") or []]
    if reasons:
        cr_props["gateReasons"] = reasons
    if record.get("degraded"):
        cr_props["degraded"] = True
    cr_props["exportedResults"] = len(pairs)
    run = {
        "tool": {"driver": {
            "name": "CodeReview",
            "fullName": "CodeReview — multi-model code review "
                        "with a deterministic gate",
            "version": str(record.get("version") or core.VERSION),
            "rules": _build_rules(pairs),
        }},
        "results": [_result(f, state) for f, state in pairs],
        "properties": {"codereview": cr_props},
    }
    return {"$schema": SARIF_SCHEMA_URL,
            "version": SARIF_VERSION,
            "runs": [run]}
