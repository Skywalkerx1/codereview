#!/usr/bin/env python3
"""codereview disputes — the computed open-dispute inventory,
the append-only disposition store, the release-flow freshness
check, the deterministic authority-affecting tagger, and quote
anchoring (`locate`).

Process tooling from the open-refutations solution §5
(owner-adopted 2026-11-04) and the step4 four-disputed expert
solution (disposition types, §4 reason fields):

- §5.1: the inventory is COMPUTED from the records, never
  reconstructed by hand. `codereview disputes` scans every
  review-*/ record for findings in a human-decision state
  (status `disputed` or `refutation_weak`) with no entry in
  the disposition store.
- §5.2: dispositions live in an append-only store,
  `dispositions.jsonl` at the repo root, keyed by finding
  fingerprint. A disposition is never edited or deleted; a
  later decision that replaces one is an OVERRIDE entry that
  references the entry it supersedes. `record-verify` consults
  the store: a disputed finding with an entry counts as
  dispositioned; without one it does not.
- §5.3: `codereview disputes --check --span A..B` is the
  release-flow freshness gate: a span may not ship carrying a
  dispute that is neither dispositioned nor inventoried.
- §5.5: "protected class" becomes a deterministic tag —
  AUTHORITY-AFFECTING: the defect could change who decides
  (role/seat assignment), whether independence holds (family
  attribution), whether a precedent or decision is valid
  (precedent keys, decision cache), whether eligibility passes
  (coverage, quorum, finder confirmation, record-verify), or
  what leaves the machine (redaction, tier policy, --private,
  public records). Report rendering and prompt display
  truncation are explicitly NOT authority-affecting. The tag
  decides who is FINAL (the owner), never who does the work.
- §5.6 + step4 solution §4: findings are anchored by their
  validated quote, not by a bare line number; `line_basis`
  records the numbering basis (diff-relative vs blob at the
  reviewed commit) and `codereview locate` resolves a quote to
  its blob positions at the reviewed commit. Disposition
  entries carry the reason fields — `reason_check`,
  `reason_corrected`, `basis_evidence` — so a right conclusion
  carried by a wrong reason is data, not a new state.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess

from . import core

DISPOSITIONS_SCHEMA = "codereview.dispositions/1"
STORE_FILENAME = "dispositions.jsonl"

DISPOSITION_TYPES = (
    "sustain_refutation", "sustain_finding", "split", "fixed",
    "retired_archived_subject", "retired_out_of_scope",
    "superseded", "downgraded")
DECIDERS = ("owner", "tech_lead", "probe")
REASON_CHECKS = ("verified", "unverified", "contradicted")
MARKERS = ("ratified", "override")
OPEN_STATUSES = ("disputed", "refutation_weak")

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


# ------------------------------------------------- authority tagger (§5.5)

DIM_WHO_DECIDES = "who decides"
DIM_INDEPENDENCE = "independence"
DIM_VALIDITY = "precedent/decision validity"
DIM_ELIGIBILITY = "eligibility"
DIM_EGRESS = "what leaves the machine"

# Keyword rules over the finding's title + category + file.
# Each rule is (dimension, [regex, ...]); matching is on the
# lowercased text. The sets are deliberately narrow: a tag that
# fires on everything recreates the owner-as-judge problem the
# definition exists to avoid (§5.5, risks table).
_KEYWORD_RULES = (
    (DIM_WHO_DECIDES, (
        r"tech lead", r"adjudicat", r"\broles?\b", r"\bseats?\b",
        r"seat[-_ ]meta", r"lens[-_ ]seat")),
    (DIM_INDEPENDENCE, (
        r"independen", r"\bfamil\w*", r"cross[- ]family")),
    (DIM_VALIDITY, (
        r"precedent", r"decision cache", r"cache key",
        r"fingerprint")),
    (DIM_ELIGIBILITY, (
        r"coverage", r"quorum", r"finder confirmation",
        r"record[-_ ]verify", r"verify[-_ ]chain", r"eligib",
        r"gate (logic|integrity)", r"\bbatch\w*")),
    (DIM_EGRESS, (
        r"redact", r"\btier\b", r"private", r"\bleaks?\b",
        r"public record", r"\bsecret\b")),
)

# Path rules over the finding's cited file: the two artifact
# classes whose every dispute is authority-affecting by nature
# (the precedent store itself, and the published attempts
# ledger). Broad source paths (core.py, cli.py, providers.py)
# are NOT path rules — the keyword rules decide there, so a
# provider-construction finding is not tagged merely for living
# in providers.py.
_PATH_RULES = (
    (DIM_VALIDITY, (r"(^|/)precedents\.json$",)),
    (DIM_EGRESS, (r"gate-attempts",)),
)

# Exclusions (§5.5): report rendering and prompt display
# truncation are not authority-affecting. An exclusion applies
# only when no HARD keyword matched — a rendering-shaped title
# on a finding that also turns on precedent keys or family
# attribution is still authority-affecting.
_EXCLUSION_RES = (
    r"_finding_public", r"prompt (display|truncation|slicing)",
    r"truncat\w* (for|in|into) prompts?", r"\brender\w*",
    r"markdown", r"gate line", r"summary (line|count)")
_HARD_KEYWORD_RES = (
    r"precedent", r"\bfamil\w*", r"independen", r"\bseats?\b",
    r"\broles?\b", r"quorum", r"coverage", r"record[-_ ]verify",
    r"redact", r"\btier\b", r"tech lead", r"adjudicat")


def _finding_text(finding):
    return " ".join(str(finding.get(k) or "") for k in
                    ("title", "category", "file")).lower()


def tag_authority(finding, overrides=None):
    """Deterministic authority-affecting tag (§5.5).

    `overrides` is {"authority": [finding_id, ...],
    "not_authority": [finding_id, ...]} — the short manual
    override list; an override always wins and says so in the
    returned reasons. Returns {"authority_affecting": bool,
    "dimensions": [...], "reasons": [...]}."""
    fid = str(finding.get("id") or "")
    ov = overrides or {}
    if fid and fid in (ov.get("not_authority") or []):
        return {"authority_affecting": False, "dimensions": [],
                "reasons": ["manual override: not authority-"
                            "affecting"]}
    if fid and fid in (ov.get("authority") or []):
        return {"authority_affecting": True, "dimensions": [],
                "reasons": ["manual override: authority-"
                            "affecting"]}
    text = _finding_text(finding)
    path = str(finding.get("file") or "")
    dimensions, reasons = [], []

    def hit(dim, why):
        if dim not in dimensions:
            dimensions.append(dim)
        reasons.append(why)

    for dim, patterns in _PATH_RULES:
        for pat in patterns:
            if re.search(pat, path):
                hit(dim, f"path {path!r} matches {pat!r} ({dim})")
    for dim, patterns in _KEYWORD_RULES:
        for pat in patterns:
            if re.search(pat, text):
                hit(dim, f"keyword {pat!r} ({dim})")
    hard = any(re.search(pat, text) for pat in _HARD_KEYWORD_RES)
    excluded = [pat for pat in _EXCLUSION_RES
                if re.search(pat, text)]
    if excluded and not hard:
        return {"authority_affecting": False, "dimensions": [],
                "reasons": [
                    f"excluded: {pat!r} — report rendering / "
                    f"prompt display is not authority-affecting"
                    for pat in excluded]}
    return {"authority_affecting": bool(dimensions),
            "dimensions": dimensions, "reasons": reasons}


# ------------------------------------------------------- disposition store

def store_path_for(repo):
    return os.path.join(repo, STORE_FILENAME)


def entry_hash(entry):
    """Content hash of a store entry: sha256 of its canonical
    JSON (sorted keys, compact separators). Entries never carry
    their own hash; an override references the superseded
    entry by this computed hash."""
    canon = json.dumps(entry, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_store(path):
    """Read the disposition store. Returns {"entries": [...],
    "problems": [...]}. A missing file is an empty store, not
    an error (the store is created lazily on first append)."""
    entries, problems = [], []
    if not path or not os.path.isfile(path):
        return {"entries": entries, "problems": problems}
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                problems.append(f"{path}:{lineno}: invalid "
                                f"JSON ({exc})")
                continue
            if isinstance(obj, dict) and \
                    obj.get("schema") == DISPOSITIONS_SCHEMA and \
                    "finding_id" not in obj:
                continue  # the header line
            if not isinstance(obj, dict) \
                    or "finding_id" not in obj:
                problems.append(f"{path}:{lineno}: not a "
                                f"disposition entry")
                continue
            entries.append(obj)
    return {"entries": entries, "problems": problems}


def validate_entry(entry, existing=()):
    """Validate a disposition entry against the schema and the
    entries already in the store. Returns a list of problems
    (empty = valid). The append-only rule: a fingerprint may be
    dispositioned once; a second entry for the same fingerprint
    is valid only as an OVERRIDE that supersedes a named prior
    entry for that fingerprint."""
    problems = []
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    fid = entry.get("finding_id")
    if not isinstance(fid, str) or not _FINGERPRINT_RE.match(fid):
        problems.append("finding_id must be a 12-char lowercase "
                        "hex fingerprint")
    typ = entry.get("type")
    if typ not in DISPOSITION_TYPES:
        problems.append(f"type must be one of "
                        f"{list(DISPOSITION_TYPES)}")
    if entry.get("decider") not in DECIDERS:
        problems.append(f"decider must be one of "
                        f"{list(DECIDERS)}")
    date = entry.get("date")
    if not isinstance(date, str) or not date:
        problems.append("date is required (ISO 8601)")
    else:
        try:
            datetime.datetime.fromisoformat(
                date.replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"date {date!r} is not ISO 8601")
    rc = entry.get("reason_check")
    if rc is not None and rc not in REASON_CHECKS:
        problems.append(f"reason_check must be one of "
                        f"{list(REASON_CHECKS)}")
    if entry.get("reason_corrected") is not None and not \
            isinstance(entry.get("reason_corrected"), str):
        problems.append("reason_corrected must be a string")
    basis = entry.get("basis_evidence")
    if basis is not None:
        if not isinstance(basis, list) or not all(
                isinstance(h, str) and _SHA256_RE.match(h)
                for h in basis):
            problems.append("basis_evidence must be a list of "
                            "sha256 hashes")
    commit = entry.get("commit")
    if typ == "fixed" and not commit:
        problems.append("a `fixed` disposition requires the "
                        "fix commit")
    if commit is not None and not (
            isinstance(commit, str) and _COMMIT_RE.match(commit)):
        problems.append("commit must be a hex commit id "
                        "(7-64 chars)")
    marker = entry.get("marker", "ratified")
    if marker not in MARKERS:
        problems.append(f"marker must be one of {list(MARKERS)}")
    prior = [e for e in existing
             if e.get("finding_id") == fid]
    if prior and marker != "override":
        problems.append(
            f"finding {fid} already has a disposition; a second "
            f"entry must be an override (marker='override') "
            f"naming the entry it supersedes")
    if marker == "override":
        sup = entry.get("supersedes")
        if not sup:
            problems.append("an override entry must name the "
                            "superseded entry (supersedes = its "
                            "entry hash)")
        elif not prior or sup not in {entry_hash(e)
                                      for e in prior}:
            problems.append("supersedes does not match any prior "
                            "entry for this finding")
    return problems


def append_entry(path, entry):
    """Validate and append one entry to the store, creating the
    store (with its header line) when absent. Returns the stored
    entry (defaults filled). Raises ValueError with every
    problem named when the entry — or the existing store — is
    not valid: a corrupt store is never appended to silently."""
    loaded = load_store(path)
    if loaded["problems"]:
        raise ValueError("the disposition store has problems; "
                         "refusing to append: "
                         + "; ".join(loaded["problems"]))
    stored = dict(entry)
    stored.setdefault("date", _now_iso())
    stored.setdefault("marker", "ratified")
    problems = validate_entry(stored, loaded["entries"])
    if problems:
        raise ValueError("; ".join(problems))
    os.makedirs(os.path.dirname(os.path.abspath(path)),
                exist_ok=True)
    fresh = not os.path.isfile(path)
    needs_nl = False
    if not fresh:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() > 0:
                fh.seek(-1, os.SEEK_END)
                needs_nl = fh.read(1) != b"\n"
    with open(path, "a", encoding="utf-8") as fh:
        if fresh:
            fh.write(json.dumps(
                {"schema": DISPOSITIONS_SCHEMA,
                 "kind": "dispositions",
                 "created_at": _now_iso()},
                ensure_ascii=False) + "\n")
        elif needs_nl:
            fh.write("\n")
        fh.write(json.dumps(stored, ensure_ascii=False,
                            sort_keys=True) + "\n")
    return stored


def dispositioned_ids(entries):
    """Finding fingerprints the store dispositions (any entry;
    an override replaces its target but the finding stays
    dispositioned)."""
    return {str(e.get("finding_id")) for e in entries or []
            if e.get("finding_id")}


def consumed_entries(entries, finding_ids):
    """The store entries record-verify consumed for a set of
    finding ids — what was relied on, reported, never hidden."""
    wanted = set(finding_ids or ())
    return [e for e in entries or []
            if e.get("finding_id") in wanted]


# ------------------------------------------------------- record scanning

def iter_record_files(root):
    """Record JSONs under the top-level review-*/ and review_*/
    directories of `root` — the committed run output. Companion
    .md files and evidence sidecars are not records."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not (name.startswith("review-")
                or name.startswith("review_")):
            continue
        dirp = os.path.join(root, name)
        if not os.path.isdir(dirp):
            continue
        for fname in sorted(os.listdir(dirp)):
            if fname.endswith(".json"):
                out.append(os.path.join(dirp, fname))
    return out


def load_record(path):
    """Parse a record file; returns the record dict, or None
    when the file is not a codereview record."""
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    if not str(rec.get("schema") or "").startswith(
            "codereview.report"):
        return None
    return rec


def _record_disputes(record):
    """Findings of one record sitting in a human-decision
    state, deduped by id (a merged finding is serialized into
    several lists). Status comes from the finding's own status
    field, falling back to list membership — the two agree in
    every record the current machinery writes."""
    found = {}
    for list_key in core._FINDING_LIST_KEYS:
        for f in record.get(list_key) or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            status = f.get("status")
            if status not in OPEN_STATUSES:
                if list_key == "disputed_findings":
                    status = "disputed"
                elif list_key == "refutation_weak_findings":
                    status = "refutation_weak"
                else:
                    continue
            cur = found.get(f["id"])
            if cur is None or (isinstance(f.get("dispute"), dict)
                               and not isinstance(
                                   cur.get("dispute"), dict)):
                g = dict(f)
                g["status"] = status
                found[f["id"]] = g
    return list(found.values())


def _lens_for(record, finding):
    """The lens that raised a finding, from the reviewer report
    that carries it (best effort; old records may not say)."""
    for rep in record.get("reviewer_reports") or []:
        if not isinstance(rep, dict):
            continue
        for f in rep.get("findings") or []:
            if isinstance(f, dict) \
                    and f.get("id") == finding.get("id"):
                return rep.get("lens")
    return None


def dispute_summary(record, finding, record_rel):
    """The inventory row for one open dispute."""
    dispute = finding.get("dispute")
    dispute = dispute if isinstance(dispute, dict) else {}
    sources = [s for s in (finding.get("sources") or [])
               if s != "deterministic"]
    return {
        "id": finding.get("id"),
        "record": record_rel,
        "status": finding.get("status"),
        "severity": finding.get("severity"),
        "category": finding.get("category"),
        "file": finding.get("file"),
        "line": finding.get("line"),
        "line_basis": finding.get("line_basis"),
        "title": finding.get("title"),
        "lens": _lens_for(record, finding),
        "raiser": sources[0] if sources else None,
        "raiser_family": dispute.get("raiser_family"),
        "refuter": dispute.get("by"),
        "refuter_family": dispute.get("family"),
        "adequacy": dispute.get("adequacy"),
        "evidence_complete": finding.get("evidence_complete"),
    }


def build_inventory(root, entries=(), overrides=None):
    """The computed inventory (§5.1): every open dispute in
    every record under `root`, split by whether the disposition
    store dispositions it. Returns {"open": [...],
    "dispositioned": [...], "records_scanned": n,
    "store_entries": n}. Each open row carries the
    authority-affecting tag."""
    disp = dispositioned_ids(entries)
    open_rows, done_rows = [], []
    scanned = 0
    seen = set()
    for path in iter_record_files(root):
        record = load_record(path)
        if record is None:
            continue
        scanned += 1
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for f in _record_disputes(record):
            row = dispute_summary(record, f, rel)
            if row["id"] in seen:
                # The same dispute serialized into a second
                # record (a copied or re-exported record file)
                # is ONE dispute: the inventory counts distinct
                # disputes, not record files (0bb1b939ab67 —
                # a duplicated record doubled the computed
                # inventory and would have doubled freshness
                # violations).
                continue
            seen.add(row["id"])
            if row["id"] in disp:
                done_rows.append(row)
            else:
                row["authority"] = tag_authority(f, overrides)
                open_rows.append(row)
    return {"open": open_rows, "dispositioned": done_rows,
            "records_scanned": scanned,
            "store_entries": len(list(entries or []))}


# ------------------------------------------------------- freshness (§5.3)

def _git_lines(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args],
                         capture_output=True, timeout=120,
                         check=False)
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").split()


def _commit_set(repo, spec):
    lines = _git_lines(repo, "rev-list", spec)
    return set(lines) if lines is not None else None


def records_touching_span(repo, root, span):
    """Split the records under `root` into (touching,
    unscoped): a record touches span A..B when its recorded
    range's commits intersect the span's, or its recorded head
    is in the span. A record with no range/head, or whose range
    cannot be recomputed, is unscoped — the check names it
    rather than silently treating it as either."""
    span_commits = _commit_set(repo, span)
    if span_commits is None:
        raise ValueError(f"span {span!r} does not resolve in "
                         f"{repo!r}")
    touching, unscoped = [], []
    for path in iter_record_files(root):
        record = load_record(path)
        if record is None:
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        commits = None
        rng = record.get("range")
        if rng:
            commits = _commit_set(repo, str(rng))
        if commits is None and record.get("head"):
            one = _git_lines(repo, "rev-parse", "--verify",
                             f"{record['head']}^{{commit}}")
            commits = set(one) if one else None
        if commits is None:
            unscoped.append(rel)
        elif commits & span_commits:
            touching.append(rel)
    return touching, unscoped


def inventory_ids_from_file(path):
    """Finding ids named by a caller-supplied inventory file:
    a JSON list of ids/rows, an object with open/items/
    open_disputes lists, or a bare ids list — including this
    command's own --json output."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    ids = set()
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("open", "items", "open_disputes"):
            if isinstance(data.get(key), list):
                items.extend(data[key])
        if isinstance(data.get("ids"), list):
            items.extend(data["ids"])
    for item in items:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict):
            fid = item.get("id") or item.get("finding_id")
            if fid:
                ids.add(str(fid))
    return ids


def check_freshness(repo, root, span, entries=(),
                    inventory_ids=()):
    """The release-flow gate (§5.3): open disputes in records
    touching `span` that are neither dispositioned by the store
    nor named in the caller's inventory. Returns {"violations":
    [row, ...], "touching": [...], "unscoped": [...]}."""
    touching, unscoped = records_touching_span(repo, root, span)
    inv = build_inventory(root, entries)
    keep = set(inventory_ids or ())
    violations = [row for row in inv["open"]
                  if row["record"] in set(touching)
                  and row["id"] not in keep]
    return {"violations": violations, "touching": touching,
            "unscoped": unscoped}


# ------------------------------------------------------- locate (§5.6)

def _full_text(container, key, evidence_dir):
    """A finding text at full length: the sidecar content when
    the record's display copy is truncated, else the record's
    own text. Returns (text, source)."""
    text = container.get(key)
    ref = container.get(key + "_ref")
    if isinstance(ref, dict) and ref.get("truncated") \
            and evidence_dir:
        path = os.path.join(evidence_dir, str(ref.get("sha256")
                                              or ""))
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read(), "sidecar"
    return (text if isinstance(text, str) else ""), "record"


def _find_finding(record, finding_id):
    for list_key in core._FINDING_LIST_KEYS:
        for f in record.get(list_key) or []:
            if isinstance(f, dict) and f.get("id") == finding_id:
                return f
    for rep in record.get("reviewer_reports") or []:
        if isinstance(rep, dict):
            for f in rep.get("findings") or []:
                if isinstance(f, dict) \
                        and f.get("id") == finding_id:
                    return f
    return None


def _quote_positions(quote, blob_text):
    """1-based blob line numbers whose text matches the quote
    under the grounding tolerances (strip, a kept '+' marker,
    whitespace collapsing), plus a whole-blob collapsed-
    substring fallback for multi-line quotes."""
    q = core._norm_quote(quote)
    if not q or not blob_text:
        return []
    positions = []
    lines = blob_text.splitlines()
    for i, line in enumerate(lines, 1):
        norm = core._norm_quote(line)
        if norm == q or (len(q) >= 8 and q in norm):
            positions.append(i)
    if positions:
        return positions
    collapsed = " ".join(blob_text.split())
    idx = collapsed.find(q)
    if idx >= 0:
        upto = collapsed[:idx]
        # Count newlines in the ORIGINAL text up to the same
        # word: approximate by word index over split lines.
        words_before = len(upto.split())
        seen = 0
        for i, line in enumerate(lines, 1):
            seen += len(line.split())
            if seen > words_before:
                return [i]
    return []


def locate_finding(record, finding_id, repo, record_dir=None):
    """Resolve a finding's validated quote to its blob
    position(s) at the reviewed commit (§5.6). The finding's
    own evidence_quote is the primary anchor; the refuter's
    dispute quote is located too when present. Legacy findings
    without line_basis, and records without a recorded head
    (the repo HEAD is used and named), locate exactly the same
    way — the quote is the anchor, not the number."""
    finding = _find_finding(record, finding_id)
    if finding is None:
        return None
    evidence_dir = (os.path.join(repo, record_dir, "evidence")
                    if repo and record_dir else None)
    quote, qsrc = _full_text(finding, "evidence_quote",
                             evidence_dir)
    quote_source = "finding"
    if not (quote or "").strip():
        dispute = finding.get("dispute")
        if isinstance(dispute, dict):
            quote, qsrc = _full_text(dispute, "evidence_quote",
                                     evidence_dir)
            quote_source = "dispute"
    ref = str(record.get("head") or "HEAD")
    blob_text, blob_error = None, ""
    path = str(finding.get("file") or "")
    if repo and path:
        try:
            blob_text = core._git_show_bytes(
                repo, f"{ref}:{path}").decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            blob_error = str(exc)
    positions = _quote_positions(quote, blob_text) \
        if blob_text is not None else []
    cited = finding.get("line")
    return {
        "finding_id": finding_id,
        "file": path,
        "title": finding.get("title"),
        "status": finding.get("status"),
        "cited_line": cited,
        "line_basis": finding.get("line_basis"),
        "quote_source": quote_source,
        "quote_from": qsrc,
        "quote": quote,
        "blob_ref": ref,
        "blob_error": blob_error or None,
        "positions": positions,
        "cited_matches": bool(
            cited is not None and cited in positions),
    }
