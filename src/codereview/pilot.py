"""B3 dev-pilot harness scaffolding (B3 design §8, 2026-11-06).

Mechanism-agnostic data collection for the B3 dev pilot. This
module deliberately contains NO promotion mechanism: no new gate
profile, no probe-promotion decision, no prediction. It provides
the three things the pilot needs regardless of which mechanism
the owner approves:

1. **The split** (§8 step 1): a deterministic hash partition of
   the pilot's dev cases into calibration and evaluation slices,
   plus a manifest that hash-commits the split inputs (salt +
   sorted case ids + the rule), so a split cannot be re-rolled
   silently — recomputing the manifest over different inputs
   yields a different `inputs_sha256`, and `verify_split_manifest`
   detects any drift between a manifest and a case set.

2. **Eligibility screening** (§3.1/§3.2): a deterministic,
   rule-based screen over a finding's own fields — blocking
   tier, a falsifiable behavioural claim in the A5 taxonomy's
   executable bases, and a concrete trigger under the same test
   B2's R4 leg uses (core._trigger_concrete). Leg 3 of §3.1
   (executable reachability in the pinned runtime) cannot be
   judged from finding text; it is NOT screened here — it
   surfaces in the probe outcome the run records, which is why
   the calibration table carries both. The screen is a
   measurement heuristic in A5's spirit (a claim-text estimate,
   not ground truth); every row records its basis so a future
   registration can re-derive or replace it.

3. **The calibration table**: per case — the live run's
   findings with eligibility and probe outcome per finding,
   and every CURRENT gate profile's verdict replayed through
   core.evaluate_gate_policy (the one evaluation entry point;
   replay = live) — plus the raw factor inputs the §8
   prediction formula consumes (p_base / p_elig / p_settle) as
   counts and ratios. The factors are INPUTS ONLY: the formula,
   its Wilson bounds, and any registration of a prediction are
   the pilot registration's business, after the owner's design
   approval — nothing here computes or registers a prediction.
"""

import copy
import hashlib
import json
import re
from collections import Counter

from . import bench as bench_mod
from . import core

SPLIT_SCHEMA = "codereview.b3-split/1"
TABLE_SCHEMA = "codereview.b3-calibration/1"
SPLIT_SALT_DEFAULT = "b3-pilot-split-v1"
SLICES = ("calibration", "evaluation")

_SPLIT_RULE = ("sha256('<salt>:<case_id>') hex digest; first 8 "
               "hex chars as an integer; even -> calibration, "
               "odd -> evaluation")


# ------------------------------------------------------------------ split

def slice_for_case(case_id, salt=SPLIT_SALT_DEFAULT):
    """The slice one case id falls in under the split rule.
    A pure function of (salt, case_id): the same inputs always
    produce the same slice, on any machine, in any order."""
    digest = hashlib.sha256(
        f"{salt}:{case_id}".encode("utf-8")).hexdigest()
    return "calibration" if int(digest[:8], 16) % 2 == 0 \
        else "evaluation"


def split_cases(case_ids, salt=SPLIT_SALT_DEFAULT):
    """Partition case ids into {calibration: [...], evaluation:
    [...]} — disjoint, exhaustive, sorted within each slice."""
    out = {name: [] for name in SLICES}
    for cid in sorted(set(case_ids)):
        out[slice_for_case(cid, salt)].append(cid)
    return out


def _split_inputs_sha256(case_ids, salt):
    payload = {"salt": salt,
               "case_ids": sorted(set(case_ids)),
               "rule": _SPLIT_RULE}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True).encode("utf-8")).hexdigest()


def build_split_manifest(case_ids, salt=SPLIT_SALT_DEFAULT):
    """The committed split manifest: the partition plus a hash
    of the exact inputs that produced it. The manifest is a
    pure function of (salt, case_ids) — no timestamps — so its
    inputs hash is stable and re-verifiable at any later date."""
    parts = split_cases(case_ids, salt)
    return {
        "schema": SPLIT_SCHEMA,
        "salt": salt,
        "rule": _SPLIT_RULE,
        "inputs_sha256": _split_inputs_sha256(case_ids, salt),
        "case_count": sum(len(v) for v in parts.values()),
        "calibration": parts["calibration"],
        "evaluation": parts["evaluation"],
    }


def verify_split_manifest(manifest, case_ids):
    """True iff `manifest` is exactly the manifest these case
    ids produce — same salt, same rule, same partition, same
    inputs hash. Any re-roll (different set, different salt,
    hand-edited slices) fails."""
    if not isinstance(manifest, dict):
        return False
    rebuilt = build_split_manifest(
        case_ids, salt=manifest.get("salt") or "")
    return all(manifest.get(k) == rebuilt.get(k) for k in (
        "schema", "salt", "rule", "inputs_sha256", "case_count",
        "calibration", "evaluation"))


# ------------------------------------------------------- eligibility (§3)

#: The executable bases of the design's §3.2 taxonomy (A5's).
EXECUTABLE_BASES = (
    "crash_or_exception", "hang_or_timeout",
    "unauthorized_access_or_bypass", "bad_input_accepted",
    "injection_or_traversal", "wrong_concrete_value",
    "duplicate_effect", "data_loss_or_destructive",
    "leak_or_exposure", "error_swallowed",
    "unbounded_resource", "secret_or_debug_artifact",
    "money_or_quantity_dropped")

#: Classes that are never probe-eligible (§3.2); the fallback
#: when no executable basis matches is "vague_or_advisory".
NONEXECUTABLE_CLASSES = (
    "missing_test_or_coverage", "style_maintainability_docs")

# Compact rule screen over title + trigger + evidence text,
# adapted from A5's pattern vocabulary (bench/analysis-2026-11-05)
# to the §3.2 basis names, in the design's order. A screening
# heuristic, recorded per finding — not a ground-truth judge.
_EXEC_PATTERNS = [
    ("crash_or_exception", re.compile(
        r"crash|exception|traceback|segfault|\bpanic\b|"
        r"null ?pointer|division by zero|index out of "
        r"(range|bounds)|typeerror|valueerror|keyerror|"
        r"throws?\b|unhandled (error|exception)", re.I)),
    ("hang_or_timeout", re.compile(
        r"hangs?\b|deadlock|infinite loop|never returns|"
        r"no timeout|missing timeout|without a timeout|"
        r"times? out|waits? forever|blocks? forever", re.I)),
    ("unauthorized_access_or_bypass", re.compile(
        r"unauthenticated|unauthori[sz]ed|without "
        r"(authentication|authori[sz]ation|permission)|"
        r"bypass|no (auth|permission|access) check|missing "
        r"(auth|permission|access) check|permission (is |was )?"
        r"never (raised|enforced)", re.I)),
    ("bad_input_accepted", re.compile(
        r"(accepts?|allows?|permits?|unvalidated|unsanitised|"
        r"unsanitized|no (input )?validation|without (any )?"
        r"(input )?validation)[^.]{0,80}(null|negative|empty|"
        r"arbitrary|malicious|oversized|user input|any "
        r"(value|input))", re.I)),
    ("injection_or_traversal", re.compile(
        r"sql injection|command injection|cross-site scripting|"
        r"\bxss\b|path traversal|directory traversal|\bssrf\b|"
        r"code injection|template injection", re.I)),
    ("wrong_concrete_value", re.compile(
        r"off-by-one|off by one|rounding|precision loss|"
        r"truncat\w+|wrong (total|amount|value|result|count|"
        r"balance)|incorrect (total|amount|value|result|count|"
        r"balance)|returns?[^.]{0,60}(wrong|incorrect|double|"
        r"twice|negative value)|(integer )?overflow|underflow",
        re.I)),
    ("duplicate_effect", re.compile(
        r"double[- ]charg|charged twice|duplicate (charge|"
        r"payment|write|record|entry|order|request)|processed "
        r"twice|runs? twice|not idempotent|no idempotency", re.I)),
    ("data_loss_or_destructive", re.compile(
        r"data loss|loses? (all )?(data|records|rows)|deletes? "
        r"(all|every)|without a where clause|no where clause|"
        r"drops? (the )?(entire )?(table|database)|destroys? "
        r"(all )?(data|records)|unconditional (row )?deletion",
        re.I)),
    ("leak_or_exposure", re.compile(
        r"(leak\w*|expos\w*|disclos\w*|plaintext|plain text|"
        r"in logs?)[^.]{0,70}(password|secret|api ?key|token|"
        r"credential|private key|sensitive)|(password|secret|"
        r"api ?key|credential|private key)[^.]{0,70}(leak\w*|"
        r"expos\w*|disclos\w*|in logs?)", re.I)),
    ("error_swallowed", re.compile(
        r"bare except|swallow\w* (the )?(error|exception|"
        r"failure)|silently (ignored|swallowed|dropped)|empty "
        r"except|catches? all exceptions|errors? (are |is )?"
        r"(silently )?(ignored|swallowed|dropped)", re.I)),
    ("unbounded_resource", re.compile(
        r"unbounded|fetches? all|loads? all|returns? all rows|"
        r"full table scan|without (a )?(limit|pagination)|"
        r"no (limit|pagination|bound)\b", re.I)),
    ("secret_or_debug_artifact", re.compile(
        r"hard ?coded [^.]{0,20}(secret|api ?key|password|"
        r"credential|token|key)|debug (mode|endpoint) "
        r"(enabled|exposed|left on)|embedded (secret|credential|"
        r"key)|debug breakpoint", re.I)),
    ("money_or_quantity_dropped", re.compile(
        r"(dollars?|amount)[^.]{0,50}(cents|dropped|ignored)|"
        r"cents[^.]{0,40}(dropped|ignored|lost)|(drops?|ignores?|"
        r"omits?) (the )?(quantity|qty|multiplier)|under-?charg\w+|"
        r"missing cents conversion", re.I)),
]

_NONEXEC_PATTERNS = [
    ("missing_test_or_coverage", re.compile(
        r"(missing|no|without|lacks?|absent)[^.]{0,40}(test|"
        r"coverage|assert)|test (is )?(disabled|skipped|missing)|"
        r"disabled test|not (covered|tested) by", re.I)),
    ("style_maintainability_docs", re.compile(
        r"style|naming|readability|maintainab|documentation|"
        r"comment|typo|formatting|\blint\b", re.I)),
]


def _finding_text(finding):
    parts = [finding.get("title") or "",
             finding.get("trigger") or "",
             finding.get("evidence") or "",
             finding.get("evidence_quote") or ""]
    return "\n".join(p for p in parts if p)


def classify_eligibility(finding):
    """Design §3.1 legs 1-2 as a deterministic screen.

    Returns {"eligible", "basis", "claim_class",
    "trigger_concrete", "reason"}: `basis` is the executable
    basis when the claim text matches one (else None);
    `claim_class` is the basis, a non-executable class, or
    "vague_or_advisory". Reachability (§3.1 leg 3) is not
    judged here — see the module docstring."""
    severity = str(finding.get("severity") or "").lower()
    trigger_ok = bool(core._trigger_concrete(
        finding.get("trigger")))
    text = _finding_text(finding)
    basis = None
    for name, pat in _EXEC_PATTERNS:
        if pat.search(text):
            basis = name
            break
    claim_class = basis
    if claim_class is None:
        claim_class = "vague_or_advisory"
        for name, pat in _NONEXEC_PATTERNS:
            if pat.search(text):
                claim_class = name
                break
    if severity not in bench_mod.BLOCKING_SEVERITIES:
        return {"eligible": False, "basis": basis,
                "claim_class": claim_class,
                "trigger_concrete": trigger_ok,
                "reason": "not_blocking_tier"}
    if basis is None:
        return {"eligible": False, "basis": None,
                "claim_class": claim_class,
                "trigger_concrete": trigger_ok,
                "reason": "non_executable_claim"}
    if not trigger_ok:
        return {"eligible": False, "basis": basis,
                "claim_class": claim_class,
                "trigger_concrete": False,
                "reason": "no_concrete_trigger"}
    return {"eligible": True, "basis": basis,
            "claim_class": claim_class,
            "trigger_concrete": True, "reason": "eligible"}


def finding_probe_outcome(finding):
    """The probe outcome recorded on a finding by a run, or
    None when no probe ran for it. Probes today ride the
    adjudication entry (core's Tech Lead loop); the read is
    shape-tolerant so a future gate-time probe record on the
    finding itself is picked up unchanged."""
    rec = (finding.get("adjudication") or {}).get("probe")
    if not isinstance(rec, dict):
        rec = finding.get("probe")
    if not isinstance(rec, dict):
        return None
    return {"outcome": str(rec.get("outcome") or "inconclusive"),
            "detail": str(rec.get("detail") or "")}


# ------------------------------------------------------- calibration table

def _base_findings(record):
    """The record's findings with profile demotions restored —
    the pre-profile finding set the profile replays evaluate
    (the registered scorers' convention)."""
    out = []
    for f in record.get("findings") or []:
        g = copy.deepcopy(f)
        dem = g.get("profile_demotion")
        if dem:
            g["severity"] = dem.get("from") or g.get("severity")
        out.append(g)
    return out


def _match_findings(case, findings):
    """{finding index: expected defect} under bench.score_case's
    greedy rule (worst severity first, then confidence; expected
    defects in severity order) — the same matching, exposed per
    finding so the table can mark true-defect findings."""
    order = sorted(
        range(len(findings)),
        key=lambda i: (core._SEV_RANK.get(
            findings[i].get("severity"), len(core.SEVERITIES)),
            -float(findings[i].get("confidence") or 0)))
    used = set()
    matched = {}
    for exp in sorted(case["expected"],
                      key=lambda e: core._SEV_RANK[e["severity"]]):
        for i in order:
            if i in used:
                continue
            ok, _cat = bench_mod._finding_matches(exp, findings[i])
            if ok:
                used.add(i)
                matched[i] = exp
                break
    return matched


def _profile_verdicts(case, base, family_by_source, profiles):
    """Replay every current profile over the base findings
    through the one evaluation entry point and record the
    per-profile primitives: whether the case blocks, how many
    blocking findings stand, and how many expected defects a
    blocking finding matches (bench.score_case)."""
    outcomes = {}
    for f in base:
        corr = f.get("corroboration") or {}
        if corr and f.get("id"):
            outcomes[f["id"]] = corr
    verdicts = {}
    for profile in profiles:
        applied, demotions = core.evaluate_gate_policy(
            copy.deepcopy(base), profile,
            family_by_source=family_by_source,
            confirmation_outcomes=outcomes)
        scored = bench_mod.score_case(case, applied)
        blocking = [f for f in applied
                    if (f.get("severity") or "").lower()
                    in bench_mod.BLOCKING_SEVERITIES]
        verdicts[profile] = {
            "blocked": bool(blocking),
            "blocking_findings": len(blocking),
            "defects_blocked": sum(
                1 for d in scored["defects"]
                if d["matched"] and not d["escaped"]),
            "defects_matched": scored["matched"],
            "demotions": len(demotions),
        }
    return verdicts


def _ratio(num, den):
    return (num / den) if den else None


def _slice_factors(rows, profiles):
    """The §8 prediction factors as RAW INPUTS (counts +
    ratios) over one slice's case rows. Not a prediction: the
    formula and its bounds belong to the pilot registration."""
    defect = [r for r in rows if r["expected_total"] > 0]
    clean = [r for r in rows if r["expected_total"] == 0]
    base_blocking = [r for r in defect
                     if r["base_blocking_without_probes"]]
    remaining = [r for r in defect
                 if not r["base_blocking_without_probes"]]
    elig_cases = [r for r in remaining
                  if r["has_eligible_e3_blocking"]]
    elig_true = [fr for r in defect for fr in r["findings"]
                 if fr["eligibility"]["eligible"]
                 and fr["matches_expected_defect"]]
    probed = [fr for fr in elig_true
              if fr["probe_outcome"] is not None]
    blocking_rows = [fr for r in rows for fr in r["findings"]
                     if fr["blocking_tier"]]
    return {
        "defect_cases": len(defect),
        "clean_cases": len(clean),
        # p_base: share of defect cases already blocking
        # without probes (a matched defect carried by an
        # E0/E1 blocking finding in the base set).
        "p_base_inputs": {
            "defect_cases": len(defect),
            "blocking_without_probes": len(base_blocking),
            "ratio": _ratio(len(base_blocking), len(defect))},
        # p_elig: share of the REMAINING defect cases with at
        # least one eligible E3 blocking finding.
        "p_elig_inputs": {
            "remaining_defect_cases": len(remaining),
            "with_eligible_e3_blocking_finding": len(elig_cases),
            "ratio": _ratio(len(elig_cases), len(remaining))},
        # p_settle: share of eligible true-defect findings
        # whose probes settle. No settlement vocabulary exists
        # before the mechanism is approved, so the inputs are
        # the probe-outcome counts themselves.
        "p_settle_inputs": {
            "eligible_true_defect_findings": len(elig_true),
            "with_probe_outcome": len(probed),
            "outcome_histogram": dict(Counter(
                fr["probe_outcome"]["outcome"] for fr in probed)),
            "note": "raw probe outcomes under the existing "
                    "falsification channel; a settlement rate "
                    "exists only once a promotion mechanism is "
                    "approved and run"},
        "eligibility": {
            "blocking_findings": len(blocking_rows),
            "eligible": sum(1 for fr in blocking_rows
                            if fr["eligibility"]["eligible"]),
            "by_basis": dict(Counter(
                fr["eligibility"]["basis"] for fr in blocking_rows
                if fr["eligibility"]["basis"])),
            "ineligible_reasons": dict(Counter(
                fr["eligibility"]["reason"] for fr in blocking_rows
                if not fr["eligibility"]["eligible"])),
        },
        "clean_blocked_by_profile": {
            p: {"cases": len(clean),
                "blocked": sum(1 for r in clean
                               if r["profiles"][p]["blocked"]),
                "ratio": _ratio(
                    sum(1 for r in clean
                        if r["profiles"][p]["blocked"]),
                    len(clean))}
            for p in profiles},
        "defect_blocked_by_profile": {
            p: {"cases": len(defect),
                "cases_blocked": sum(
                    1 for r in defect if r["profiles"][p]["blocked"]),
                "defects_blocked": sum(
                    r["profiles"][p]["defects_blocked"]
                    for r in defect),
                "defects_total": sum(r["expected_total"]
                                     for r in defect)}
            for p in profiles},
    }


def build_calibration_table(records, cases, family_by_source,
                            split_manifest=None,
                            profiles=core.GATE_PROFILES):
    """Assemble the calibration table from live-run records.

    `records`: bench-shaped result records (bench.run_bench /
    pilot runner output). `cases`: bench.load_case-shaped case
    dicts (id + expected at minimum). `family_by_source`: seat
    name -> vendor family for the profile replays (the config's
    seat_meta families, plus "deterministic"). When
    `split_manifest` is given it must be the manifest these
    cases produce (verified) and it assigns the slices; without
    one, the split is computed from the case ids directly."""
    cases_by_id = {c["id"]: c for c in cases}
    if split_manifest is not None:
        if not verify_split_manifest(split_manifest,
                                     sorted(cases_by_id)):
            raise ValueError(
                "split manifest does not match the case set "
                "(inputs hash / partition drift) — refusing to "
                "build a table on a re-rolled split")
        slice_of = {}
        for name in SLICES:
            for cid in split_manifest[name]:
                slice_of[cid] = name
        manifest_ref = split_manifest["inputs_sha256"]
    else:
        parts = split_cases(sorted(cases_by_id))
        slice_of = {cid: name for name in SLICES
                    for cid in parts[name]}
        manifest_ref = _split_inputs_sha256(
            sorted(cases_by_id), SPLIT_SALT_DEFAULT)
    rows = []
    for rec in records:
        cid = rec.get("case_id")
        case = cases_by_id.get(cid)
        if case is None:
            raise ValueError(
                f"calibration record names unknown case {cid!r}")
        base = _base_findings(rec)
        matched = _match_findings(case, base)
        finding_rows = []
        for i, f in enumerate(base):
            exp = matched.get(i)
            finding_rows.append({
                "finding_id": f.get("id"),
                "severity": f.get("severity"),
                "category": f.get("category"),
                "file": f.get("file"),
                "line": f.get("line"),
                "title": f.get("title"),
                "sources": list(f.get("sources") or []),
                "evidence_class": f.get("evidence_class"),
                "blocking_tier": (f.get("severity") or "").lower()
                    in bench_mod.BLOCKING_SEVERITIES,
                "eligibility": classify_eligibility(f),
                "probe_outcome": finding_probe_outcome(f),
                "matches_expected_defect": exp is not None,
                "expected_defect": (
                    {"severity": exp["severity"],
                     "file": exp["file"], "line": exp.get("line"),
                     "title": exp["title"]} if exp else None),
            })
        rows.append({
            "case_id": cid,
            "slice": slice_of[cid],
            "stratum": "defect" if case["expected"] else "clean",
            "expected_total": len(case["expected"]),
            "live_gate": rec.get("gate"),
            "live_profile": (rec.get("gate_profile") or {}).get(
                "profile"),
            "degraded": bool(rec.get("degraded")),
            "base_blocking_without_probes": any(
                fr["matches_expected_defect"] and fr["blocking_tier"]
                and fr["evidence_class"] in ("E0", "E1")
                for fr in finding_rows),
            "has_eligible_e3_blocking": any(
                fr["eligibility"]["eligible"] and fr["blocking_tier"]
                and fr["evidence_class"] == "E3"
                for fr in finding_rows),
            "findings": finding_rows,
            "profiles": _profile_verdicts(
                case, base, family_by_source, profiles),
        })
    rows.sort(key=lambda r: r["case_id"])
    by_slice = {name: [r for r in rows if r["slice"] == name]
                for name in SLICES}
    return {
        "schema": TABLE_SCHEMA,
        "split_manifest_inputs_sha256": manifest_ref,
        "profiles": list(profiles),
        "cases": rows,
        "factors": {
            "calibration": _slice_factors(
                by_slice["calibration"], profiles),
            "evaluation": _slice_factors(
                by_slice["evaluation"], profiles),
            "all": _slice_factors(rows, profiles),
        },
    }
