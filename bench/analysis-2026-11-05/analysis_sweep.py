#!/usr/bin/env python3
"""B2 Step-1 offline analyses A2-A5 (2026-11-05). READ-ONLY inputs:
registered result records + corpus. Never writes outside this dir.

Definitions (per the Step-1 brief, exactly):
- Live grouping = merged findings AS STORED in the result records.
- Live matching = codereview.bench _finding_matches / score_case.
- Merged blocking precision = bench/scripts/score_confirmation_v2
  .merged_blocking_precision semantics (imported, not re-derived).
- Base severity = profile_demotion.from if present else severity.
- Evidence class computed from sources: E0 if "deterministic" in
  sources; else E1 if sources span >= 2 distinct FAMILIES (panel
  seat_meta family map); else E3. E2 never occurs offline.
- Public ground truth = ORIGINAL labels only: expected entries
  carrying an "adjudication_added" marker are excluded.
- BLOCKING = severity in (blocker, major).

Step 2+3 refactor (expert solution §6.1 — replay = live): the A3
rule transforms no longer re-derive policy behaviour locally.
R0/R1/R2/R3 severities come from the product's ONE evaluation
entry point, core.evaluate_gate_policy (grouping included),
with the panel family map for B2's family-aware classes and
require_trigger=False (the stored findings predate the trigger
field; R4 stays a pilot item, exactly as Step 1 concluded).
The local evidence_class() below remains only for A2/A4/A5's
descriptive tallies.
"""
import copy
import importlib.util
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # repo root
sys.path.insert(0, os.path.join(ROOT, "src"))

from codereview import bench as bench_mod  # noqa: E402
from codereview import core as core_mod  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "score_confirmation_v2",
    os.path.join(ROOT, "bench", "scripts", "score_confirmation_v2.py"))
scorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scorer)
merged_blocking_precision = scorer.merged_blocking_precision

BLOCKING = ("blocker", "major")
SEATS = ["deepseek", "openai", "nvidia", "deterministic"]

# Family map from bench/configs/panel-baseline-2026-11-04.json seat_meta
_panel = json.load(open(os.path.join(
    ROOT, "bench", "configs", "panel-baseline-2026-11-04.json"),
    encoding="utf-8"))
FAMILY = {seat: meta["family"] for seat, meta in
          (_panel.get("seat_meta") or {}).items()}
FAMILY.setdefault("deterministic", "deterministic")


# ---------------------------------------------------------------- helpers

def base_severity(f):
    dem = f.get("profile_demotion")
    if dem and dem.get("from"):
        return dem["from"]
    return f.get("severity")


def base_findings(rec):
    out = []
    for f in rec["findings"]:
        g = copy.deepcopy(f)
        g["severity"] = base_severity(f)
        out.append(g)
    return out


def evidence_class(f):
    sources = f.get("sources") or []
    if "deterministic" in sources:
        return "E0"
    fams = {FAMILY.get(s, s) for s in sources}
    if len(fams) >= 2:
        return "E1"
    return "E3"


def is_blocking(sev):
    return (sev or "").lower() in BLOCKING


def read_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")
            if l.strip()]


def load_cases_filtered():
    """Corpus cases; public cases carry ORIGINAL labels only."""
    corpus_dir = os.path.join(ROOT, "bench", "corpus")
    cases = {}
    for cid in sorted(os.listdir(corpus_dir)):
        cdir = os.path.join(corpus_dir, cid)
        if not os.path.isdir(cdir):
            continue
        case = bench_mod.load_case(cdir)
        if case["split"] == "public":
            raw = json.load(open(os.path.join(cdir, "case.json"),
                                 encoding="utf-8"))
            kept = [e for e in raw.get("expected") or []
                    if "adjudication_added" not in e]
            case = dict(case)
            case["expected"] = [
                bench_mod._validate_expected(
                    cid, e, os.path.join(cdir, "case.json"))
                for e in kept]
            case["expected_total_raw"] = len(raw.get("expected") or [])
        cases[cid] = case
    return cases


def greedy_matches(case, findings):
    """Replicate bench.score_case's greedy matching, returning for
    each expected defect (in score_case's defect order) the matched
    finding object or None. Findings keep the severity the caller
    put on them (A2 passes base-severity findings)."""
    order = sorted(
        range(len(findings)),
        key=lambda i: (core_mod._SEV_RANK.get(
            findings[i].get("severity"), len(core_mod.SEVERITIES)),
            -float(findings[i].get("confidence") or 0)))
    used = set()
    rows = []
    for exp in sorted(case["expected"],
                      key=lambda e: core_mod._SEV_RANK[e["severity"]]):
        hit = None
        for i in order:
            if i in used:
                continue
            ok, _ = bench_mod._finding_matches(exp, findings[i])
            if ok:
                hit = findings[i]
                used.add(i)
                break
        rows.append({"expected": exp, "finding": hit})
    return rows


# ---------------------------------------------------------------- load

CASES = load_cases_filtered()
ATT = read_jsonl(os.path.join(ROOT, "bench", "generation-v2",
                              "attempt-1.jsonl"))
PUB = read_jsonl(os.path.join(ROOT, "bench",
                              "baseline-2026-11-04-results.jsonl"))
ATT_HOLDOUT = [r for r in ATT if r["split"] == "holdout"]
ATT_EXPANDED = [r for r in ATT if r["split"] == "expanded-clean"]
PUB_DEFECT = [r for r in PUB if CASES[r["case_id"]]["expected"]]
PUB_CLEAN = [r for r in PUB if not CASES[r["case_id"]]["expected"]]
HOLDOUT_DEFECT = [r for r in ATT_HOLDOUT
                  if CASES[r["case_id"]]["expected"]]
HOLDOUT_CLEAN = [r for r in ATT_HOLDOUT
                 if not CASES[r["case_id"]]["expected"]]


def pct(num, den):
    return (num / den) if den else None


# ---------------------------------------------------------------- A2

def a2_for(pairs):
    """pairs: [(case, record)] over defect-bearing cases."""
    matched_findings = []       # one per matched defect
    per_defect = []
    case_classes = {}
    for case, rec in pairs:
        rows = greedy_matches(case, base_findings(rec))
        case_blocking_classes = []
        for row in rows:
            f = row["finding"]
            if f is None:
                per_defect.append({"case_id": case["id"],
                                   "matched": False})
                continue
            ec = evidence_class(f)
            blk = is_blocking(f.get("severity"))
            matched_findings.append(
                {"case_id": case["id"], "finding_id": f.get("id"),
                 "evidence_class": ec, "blocking_base": blk})
            survives = bool(blk and ec in ("E0", "E1", "E2"))
            per_defect.append({
                "case_id": case["id"], "matched": True,
                "finding_id": f.get("id"), "evidence_class": ec,
                "blocking_base": blk, "survives_block_e01": survives})
            if blk:
                case_blocking_classes.append(ec)
        if case_blocking_classes:
            s = set(case_blocking_classes)
            if s <= {"E0", "E1", "E2"}:
                cls = "ALL_BLOCKING_TP_E01"
            elif s == {"E3"}:
                cls = "ALL_BLOCKING_TP_E3"
            else:
                cls = "MIXED"
        else:
            cls = "NO_BLOCKING_TP"
        case_classes[case["id"]] = cls

    # Supplementary (labelled as such): any-match survival — a
    # defect also survives if ANY blocking (base) E0/E1 finding in
    # its record matches it, even when the greedy TP finding is a
    # different (E3) one. This is score_confirmation_v2's D
    # semantics, NOT the brief's greedy-TP definition above.
    any_surviving = 0
    for case, rec in pairs:
        bfs = base_findings(rec)
        for exp in case["expected"]:
            if any(is_blocking(f.get("severity"))
                   and evidence_class(f) in ("E0", "E1", "E2")
                   and bench_mod._finding_matches(exp, f)[0]
                   for f in bfs):
                any_surviving += 1

    def dist(findings):
        c = Counter(f["evidence_class"] for f in findings)
        n = len(findings)
        e01 = c.get("E0", 0) + c.get("E1", 0)
        return {"n": n, "E0": c.get("E0", 0), "E1": c.get("E1", 0),
                "E3": c.get("E3", 0), "pct_E01": pct(e01, n),
                "pct_E3": pct(c.get("E3", 0), n)}

    total_defects = len(per_defect)
    matched_n = sum(1 for d in per_defect if d["matched"])
    surviving = sum(1 for d in per_defect if d.get("survives_block_e01"))
    nonblocking_tp = sum(1 for d in per_defect
                         if d["matched"] and not d["blocking_base"])
    blocking_e3 = sum(1 for d in per_defect if d["matched"]
                      and d["blocking_base"]
                      and d["evidence_class"] == "E3")
    case_dist = Counter(case_classes.values())
    n_cases = len(case_classes)
    return {
        "defects_total": total_defects,
        "defects_matched": matched_n,
        "finding_level": {
            "all_matched": dist(matched_findings),
            "blocking_only_base": dist(
                [f for f in matched_findings if f["blocking_base"]]),
        },
        "defect_survival_block_only_E01": {
            "surviving": surviving,
            "pct_surviving": pct(surviving, total_defects),
            "matched_but_nonblocking_TP": nonblocking_tp,
            "matched_blocking_but_E3": blocking_e3,
            "unmatched": total_defects - matched_n,
            "supplementary_any_match_surviving": any_surviving,
            "supplementary_any_match_pct": pct(any_surviving,
                                               total_defects),
        },
        "case_level": {
            "defect_cases": n_cases,
            "distribution": {k: case_dist.get(k, 0) for k in (
                "ALL_BLOCKING_TP_E01", "MIXED", "ALL_BLOCKING_TP_E3",
                "NO_BLOCKING_TP")},
            "pct_ALL_BLOCKING_TP_E01": pct(
                case_dist.get("ALL_BLOCKING_TP_E01", 0), n_cases),
            "per_case": case_classes,
        },
        "per_defect": per_defect,
    }


def run_a2():
    a5_pairs = [(CASES[r["case_id"]], r) for r in HOLDOUT_DEFECT]
    pub_pairs = [(CASES[r["case_id"]], r) for r in PUB_DEFECT]
    a5 = a2_for(a5_pairs)
    pub = a2_for(pub_pairs)
    comb = a2_for(a5_pairs + pub_pairs)
    return {
        "analysis": "A2 corroboration cost",
        "definitions": {
            "matching": "score_case greedy algorithm replicated on "
                        "BASE-severity findings (severity ordering "
                        "uses base severity; _finding_matches is "
                        "severity-independent)",
            "evidence_class": "computed from sources via family "
                              "map; stored field not trusted",
            "sets": "a5 = 7 holdout defect cases (7 defects); "
                    "public = 22 public defect cases (24 original-"
                    "label defects); combined = 31 defects",
        },
        "a5": a5, "public": pub, "combined": comb,
        "decision_numbers": {
            "combined_pct_TP_findings_blocking_E01":
                comb["finding_level"]["blocking_only_base"]["pct_E01"],
            "combined_pct_defects_surviving":
                comb["defect_survival_block_only_E01"]["pct_surviving"],
        },
    }


# ---------------------------------------------------------------- A3

BASELINE_LENS = {"openai": "correctness", "deepseek": "correctness",
                 "nvidia": "operations", "deterministic": "deterministic"}


def tf_r0(rec):
    applied, _dem = core_mod.evaluate_gate_policy(
        base_findings(rec), "strict", family_by_source=FAMILY,
        require_trigger=False)
    return applied


def tf_r1(rec, source):
    if source == "attempt":
        return copy.deepcopy(rec["findings"])  # stored severities ARE B1
    # public: stamp source_lenses from reviewer_reports, then the
    # product's one evaluation entry point under B1.
    lens_by_provider = {}
    for rep in rec.get("reviewer_reports") or []:
        prov, lens = rep.get("provider"), rep.get("lens")
        if prov and lens:
            lens_by_provider.setdefault(prov, set()).add(lens)
    out = []
    for f in rec["findings"]:
        g = copy.deepcopy(f)
        sl = {}
        for src in g.get("sources") or []:
            if src == "deterministic":
                sl[src] = ["deterministic"]
            elif src in lens_by_provider:
                sl[src] = sorted(lens_by_provider[src])
            elif src in BASELINE_LENS:
                sl[src] = [BASELINE_LENS[src]]
        g["source_lenses"] = sl
        out.append(g)
    applied, _dem = core_mod.evaluate_gate_policy(
        out, "balanced", require_trigger=False)
    return applied


def tf_r2(rec):
    # R2/R3 severities = policy B2's evidence-class demotion
    # with NO confirmation channel (offline R3 ≡ R2, as Step 1
    # stated) and no trigger rule (R4 is not evaluable offline).
    applied, _dem = core_mod.evaluate_gate_policy(
        base_findings(rec), "corroborated", family_by_source=FAMILY,
        require_trigger=False)
    return applied


def score_scope(pairs):
    """pairs: [(case, findings)] incl. clean rows (expected []).
    Returns recall + merged blocking precision."""
    matched = total = escaped = 0
    rows = []
    for case, findings in pairs:
        s = bench_mod.score_case(case, findings)
        matched += s["matched"]
        escaped += s["escaped"]
        total += s["expected_total"]
        rows.append({"expected": case["expected"],
                     "findings": findings})
    prec, D, U, dupes = merged_blocking_precision(rows)
    return {"defects_total": total, "defects_matched": matched,
            "recall": pct(matched, total),
            "supplementary_blocking_recall": pct(total - escaped,
                                                 total),
            "supplementary_escaped_defects": escaped,
            "merged_blocking_precision": prec,
            "precision_D": D, "precision_U": U,
            "precision_duplicates_removed": dupes}


def clean_blocked(pairs):
    """pairs: [(record, findings)] -> (blocked, n, rate)."""
    b = sum(1 for _r, fs in pairs
            if any(is_blocking(f.get("severity")) for f in fs))
    return b, len(pairs), pct(b, len(pairs))


def e3_blocking_counts(pairs):
    """pairs: [(case, record)] -> E3 blocking (base) counts split
    clean vs defect cases (R3 confirmation candidates)."""
    clean = defect = 0
    for case, rec in pairs:
        n = sum(1 for f in base_findings(rec)
                if is_blocking(f.get("severity"))
                and evidence_class(f) == "E3")
        if case["expected"]:
            defect += n
        else:
            clean += n
    return {"clean_cases": clean, "defect_cases": defect,
            "total": clean + defect}


def run_a3():
    rules = {}
    sanity = {}
    for rule in ("R0", "R1", "R2", "R3"):
        def tf(rec, source, _rule=rule):
            if _rule == "R0":
                return tf_r0(rec)
            if _rule == "R1":
                return tf_r1(rec, source)
            return tf_r2(rec)  # R3 severities identical to R2

        a5_pairs = [(CASES[r["case_id"]], tf(r, "attempt"))
                    for r in ATT_HOLDOUT]
        pub_pairs = [(CASES[r["case_id"]], tf(r, "public"))
                     for r in PUB]
        m_a5 = score_scope(a5_pairs)
        m_pub = score_scope(pub_pairs)
        m_comb = score_scope(a5_pairs + pub_pairs)

        exp_pairs = [(r, tf(r, "attempt")) for r in ATT_EXPANDED]
        pubc_pairs = [(r, tf(r, "public")) for r in PUB_CLEAN]
        eb, en, er = clean_blocked(exp_pairs)
        pb, pn, pr = clean_blocked(pubc_pairs)
        cb, cn, cr = clean_blocked(exp_pairs + pubc_pairs)

        def bundle(recall, rate):
            return {"recall": recall, "clean_rate": rate,
                    "J": (recall - rate) if (recall is not None
                                             and rate is not None)
                    else None,
                    "shortlist_pass": bool(
                        rate is not None and rate <= 0.15
                        and recall is not None and recall >= 0.95)}

        rules[rule] = {
            "a5": m_a5, "public": m_pub, "combined_defects": m_comb,
            "clean_blocked": {
                "expanded_clean": {"blocked": eb, "n": en, "rate": er},
                "public_clean": {"blocked": pb, "n": pn, "rate": pr},
                "combined_clean": {"blocked": cb, "n": cn, "rate": cr},
            },
            "bundles": {
                "a5": bundle(m_a5["recall"], er),
                "public": bundle(m_pub["recall"], pr),
                "combined": bundle(m_comb["recall"], cr),
            },
            "shortlist_combined_pass": bool(
                cr is not None and cr <= 0.15
                and m_comb["recall"] is not None
                and m_comb["recall"] >= 0.95),
        }
        if rule == "R0":
            sanity["R0_expanded_clean_blocked"] = f"{eb}/{en}"
            sanity["R0_expanded_clean_expected_32/34"] = (eb == 32)
            sanity["R0_a5_recall"] = m_a5["recall"]
            sanity["R0_a5_recall_is_1.000"] = (m_a5["recall"] == 1.0)
            sanity["R0_public_recall_original_labels"] = m_pub["recall"]
            sanity["R0_public_recall_is_1.000"] = (m_pub["recall"] == 1.0)
        if rule == "R1":
            sanity["R1_expanded_clean_blocked"] = f"{eb}/{en}"
            sanity["R1_expanded_clean_expected_22/34"] = (eb == 22)
            sanity["R1_a5_recall"] = m_a5["recall"]
            sanity["R1_a5_recall_is_1.000"] = (m_a5["recall"] == 1.0)

    r3_counts = {
        "a5_holdout_records": e3_blocking_counts(
            [(CASES[r["case_id"]], r) for r in ATT_HOLDOUT]),
        "public_records": e3_blocking_counts(
            [(CASES[r["case_id"]], r) for r in PUB]),
        "expanded_clean_records": e3_blocking_counts(
            [(CASES.get(r["case_id"], {"expected": []}), r)
             for r in ATT_EXPANDED]),
        "combined_all_records": e3_blocking_counts(
            [(CASES[r["case_id"]], r) for r in ATT_HOLDOUT]
            + [(CASES[r["case_id"]], r) for r in PUB]
            + [(CASES.get(r["case_id"], {"expected": []}), r)
               for r in ATT_EXPANDED]),
    }
    rules["R3"]["cross_family_confirmation_candidates"] = r3_counts
    rules["R3"]["note"] = ("R3 metrics are identical to R2 by "
                           "construction: cross-family confirmation "
                           "of E3 majors needs new model calls and "
                           "is NOT simulated offline. Counts = E3 "
                           "blocking findings (base severity) R3 "
                           "would send to confirmation.")
    rules["R1"]["note"] = ("Public R1 = the product evaluation "
                           "entry point core.evaluate_gate_policy (B1) applied to "
                           "stored merged findings after stamping "
                           "source_lenses from each record's "
                           "reviewer_reports (provider -> lens) "
                           "plus deterministic -> [deterministic]; "
                           "attempt-1 R1 = records as recorded "
                           "(stored severities/gates ARE B1).")

    # R4: trigger field check (grep-equivalent over parsed records)
    trig = sum(1 for recs in (ATT, PUB) for r in recs
               for f in r["findings"] if "trigger" in f)
    trig_keys = sorted({k for recs in (ATT, PUB) for r in recs
                        for f in r["findings"] for k in f
                        if "trigger" in k.lower()})
    rules["R4"] = {
        "status": "not evaluable offline — pilot item",
        "reason": ("Findings carry evidence_quote but no trigger "
                   "field: 0 of %d findings across both record "
                   "files carry a 'trigger' key (keys containing "
                   "'trigger': %s). No deterministic trigger "
                   "representation exists to evaluate."
                   % (sum(len(r['findings']) for recs in (ATT, PUB)
                          for r in recs), trig_keys)),
        "trigger_field_findings": trig,
    }
    return {"analysis": "A3 rule sweep",
            "rule_definitions": {
                "R0": "strict: base severities, everything blocking blocks",
                "R1": "B1 balanced gate profile (see note)",
                "R2": "from base: E3 blocking findings demoted to minor; E0/E1 unchanged",
                "R3": "severities identical to R2 by construction; E3 blocking findings counted as cross-family confirmation candidates",
                "R4": "deterministic-trigger requirement — not evaluable offline",
            },
            "scopes": {
                "a5": "recall + merged blocking precision over the 9 holdout records (2 clean controls' blocking findings count as U)",
                "public": "recall + merged blocking precision over the 27 public records (original labels, 24 defects)",
                "combined_defects": "pooled holdout + public (36 records, 31 labelled defects)",
                "clean": "expanded_clean 34, public_clean 5, combined_clean 39; blocked = any finding blocking under the rule",
            },
            "rules": rules, "sanity_checks": sanity}


# ---------------------------------------------------------------- A4

def a4_stratum(records):
    """records -> per-seat emission + agreement over BASE findings."""
    n_cases = len(records)
    findings = []
    for r in records:
        findings.extend(base_findings(r))
    seats = {}
    for seat in SEATS:
        any_src = [f for f in findings if seat in (f.get("sources") or [])]
        sole = [f for f in findings
                if (f.get("sources") or []) == [seat]]
        seats[seat] = {
            "any_source": {
                "major_only": sum(1 for f in any_src
                                  if f.get("severity") == "major"),
                "blocking": sum(1 for f in any_src
                                if is_blocking(f.get("severity"))),
            },
            "sole_source": {
                "major_only": sum(1 for f in sole
                                  if f.get("severity") == "major"),
                "blocking": sum(1 for f in sole
                                if is_blocking(f.get("severity"))),
            },
            "majors_per_case": pct(
                sum(1 for f in any_src if f.get("severity") == "major"),
                n_cases),
        }
    blocking = [f for f in findings if is_blocking(f.get("severity"))]
    totals = {s: sum(1 for f in blocking if s in (f.get("sources") or []))
              for s in SEATS}
    inter = {}
    share = {}
    for x in SEATS:
        inter[x] = {}
        share[x] = {}
        for y in SEATS:
            if x == y:
                inter[x][y] = totals[x]
                share[x][y] = 1.0
                continue
            both = sum(1 for f in blocking
                       if x in (f.get("sources") or [])
                       and y in (f.get("sources") or []))
            inter[x][y] = both
            share[x][y] = pct(both, totals[x])
    return {"cases": n_cases, "merged_findings_base_total": len(findings),
            "seats": seats,
            "agreement_blocking_base": {
                "seat_blocking_totals": totals,
                "intersection_counts": inter,
                "share_of_row_seat": share,
            }}


def run_a4():
    defect_sets = {
        "attempt_a5": HOLDOUT_DEFECT,
        "public": PUB_DEFECT,
        "combined": HOLDOUT_DEFECT + PUB_DEFECT,
    }
    clean_sets = {
        "attempt_expanded": ATT_EXPANDED,
        "public": PUB_CLEAN,
        "combined": ATT_EXPANDED + PUB_CLEAN,
    }
    return {
        "analysis": "A4 seat-level emission + agreement",
        "notes": ("Merged findings at BASE severity. any-source = "
                  "seat in sources; sole-source = sources == [seat]. "
                  "Agreement share (X,Y) = blocking findings with "
                  "both X and Y in sources / blocking findings "
                  "with X in sources; diagonal 1.0."),
        "defect_cases": {k: a4_stratum(v) for k, v in defect_sets.items()},
        "clean_cases": {k: a4_stratum(v) for k, v in clean_sets.items()},
    }


# ---------------------------------------------------------------- A5

# Transparent rule-based heuristic classifier over title+evidence.
# (pattern_name, compiled regex) — executable claims, in order.
EXEC_PATTERNS = [
    ("crash_or_exception", re.compile(
        r"crash|exception|traceback|stack overflow|segfault|\bpanic\b|"
        r"raise[sd]?\b|throws?\b|throwing\b|typeerror|valueerror|"
        r"keyerror|null ?pointer|segmentation fault|"
        r"division by zero|index out of (range|bounds)|"
        r"blocks? the migration|migration (fails?|is blocked|breaks?)")),
    ("hang_or_timeout", re.compile(
        r"hangs?\b|never returns|deadlock|infinite loop|indefinitely|"
        r"no timeout|without a timeout|missing timeout|"
        r"lacks? a timeout|times? out|waits? forever|blocks? forever")),
    ("unauthorized_access_or_bypass", re.compile(
        r"unauthenticated|unauthori[sz]ed|without authentication|"
        r"without authori[sz]ation|without (a )?(permission|auth) "
        r"check|bypass|any (reachable )?(user|caller|request)|"
        r"every request|non-staff|unprivileged|"
        r"no (auth|permission|access|authori[sz]ation) check|"
        r"missing (auth|permission|access) check|"
        r"(auth|permission|access) check (was |is )?"
        r"(removed|missing|absent|bypassed)|"
        r"permission (was |is )?never (raised|enforced)|"
        r"never raises? (permissiondenied|an? (auth|permission))")),
    ("bad_input_accepted", re.compile(
        r"(accepts?|allows?|permits?|passes|passing|forwards?|"
        r"unvalidated|unsanitised|unsanitized|no (input )?validation|"
        r"without (any )?(input )?validation)"
        r"[^.]{0,80}"
        r"(null|negative|empty|non-utf|arbitrary|malicious|"
        r"unauthenticated|oversized|user input|any (value|input))")),
    ("injection_or_traversal", re.compile(
        r"(sql injection|command injection|cross-site scripting|"
        r"\bxss\b|path traversal|directory traversal|\bssrf\b|"
        r"server-side request forgery|code injection|"
        r"template injection)"
        r"[^.]{0,200}"
        r"(attacker|user input|crafted|payload|unsanitised|"
        r"unsanitized|unescaped|concatenat|inject|parameter|"
        r"via |input|query|string)")),
    ("wrong_concrete_value", re.compile(
        r"off-by-one|off by one|round\w+|round-off|precision loss|"
        r"silently truncat\w+|truncat\w+ (at|to) \S+|stops? one page early|skips? the final page|incomplete results|decimal to float|"
        r"loses? precision|"
        r"(returns?|computes?|calculates?|yields?|produces?|gives?)"
        r"[^.]{0,60}(wrong|incorrect|negative value|double|twice)|"
        r"wrong (total|amount|value|result|count|balance)|"
        r"incorrect (total|amount|value|result|count|balance)|"
        r"floating[- ]point[^.]{0,50}(money|cent|dollar|price|total|"
        r"currency)|float[^.]{0,30}(money|monetary|currency|price)|"
        r"(integer )?overflow|underflow")),
    ("duplicate_effect", re.compile(
        r"double[- ]charg|charged twice|duplicate (charge|payment|"
        r"write|record|entry|order|request)|processed twice|"
        r"runs? twice|executed twice|not idempotent|"
        r"lacks? idempotency|no idempotency")),
    ("data_loss_or_destructive", re.compile(
        r"data loss|loses? (all )?(data|records|rows)|"
        r"deletes? (all|every) |delete[^.]{0,50}without a where|"
        r"no where clause|without a where clause|"
        r"drops? (the )?(entire )?(table|database)|drop table|"
        r"table drop|"
        r"truncates? (the )?(table|database)|"
        r"destroys? (all )?(data|records)|deletion without|unconditional (row )?deletion|deletes? (jobs|records|rows|files) for (every|each|all)")),
    ("leak_or_exposure", re.compile(
        r"(leak\w*|expos\w*|disclos\w*|log\w*|stor\w*|plaintext|"
        r"plain text|in logs?)"
        r"[^.]{0,70}"
        r"(password|secret|api ?key|access key|token|credential|"
        r"private key|sensitive)"
        r"|"
        r"(password|secret|api ?key|credential|private key)"
        r"[^.]{0,70}"
        r"(leak\w*|expos\w*|log\w*|stor\w*|plaintext|plain text|"
        r"returned|disclos\w*|in logs?)")),
    ("error_swallowed", re.compile(
        r"bare except|swallow\w* (the )?(error|exception|failure)|"
        r"silently (ignored|swallowed|dropped|discarded)|"
        r"empty except|catches? all exceptions|"
        r"errors? (are |is )?(silently )?(ignored|swallowed|dropped)")),
    ("unbounded_resource", re.compile(
        r"unbounded|fetches? all|loads? all|returns? all rows|"
        r"full table scan|alert flooding|without (a )?(limit|pagination)|"
        r"no (limit|pagination|bound)\b")),
    ("secret_or_debug_artifact", re.compile(
        r"hard ?coded [^.]{0,20}(secret|api ?key|password|credential|token|key)|"
        r"hard-?coded (secret|key)|aws (access )?key|private key|"
        r"debug breakpoint|breakpoint (left|in )|"
        r"debug (mode|endpoint) (enabled|exposed|left on)|"
        r"embedded (secret|credential|key)")),
    ("money_or_quantity_dropped", re.compile(
        r"(dollars?|amount)[^.]{0,50}(cents|dropped|ignored|"
        r"instead of cents)|cents[^.]{0,40}(dropped|ignored|lost)|"
        r"(drops?|ignores?|omits?) (the )?(quantity|qty|multiplier)|under-?charg\w+|missing cents conversion|cents conversion|(quantity|qty)[^.]{0,40}(dropped|ignored|not (sent|"
        r"included|passed))")),
]

NONEXEC_PATTERNS = [
    ("missing_test_or_coverage", re.compile(
        r"(missing|no|without|lacks?|absent)[^.]{0,40}"
        r"(test|coverage|assert)|test (is )?(disabled|skipped|"
        r"missing)|disabled test|not (covered|tested) by")),
    ("style_maintainability_docs", re.compile(
        r"style|naming|readability|maintainab|documentation|"
        r"comment|typo|formatting|\blint\b")),
    ("vague_or_advisory", re.compile(r".*")),  # fallback label
]


# Two-token rules (class token AND context/outcome token anywhere
# in the text, either order) — titles often name the class after
# the context, or in a separate sentence from the evidence.
EXEC_PAIR_RULES = [
    ("injection_or_traversal", re.compile(
        r"sql injection|command injection|cross-site scripting|"
        r"\bxss\b|path traversal|directory traversal|\bssrf\b|injection\b|injectable|"
        r"server-side request forgery|code injection|"
        r"template injection|shell command|shell execution|innerhtml|os\.system|files outside|outside the upload|"
        r"eval\("),
     re.compile(
        r"attacker|user input|user-controlled|untrusted|crafted|"
        r"payload|unsanit|sanit|unescap|concatenat|string formatting|"
        r"interpolat|inject|parameter|malicious|host argument|code execution|"
        r"search term")),
    ("race_concrete_outcome", re.compile(
        r"race condition|check-then-act|check-then-open|toctou|"
        r"time-of-check|\brace\b|concurrent|non-atomic"),
     re.compile(
        r"overwrite|truncat|lost update|negative|double|exceed|"
        r"inconsistent|bypass|corrupt|duplicate|stale|clobber|"
        r"another (caller|thread|process|request)|"
        r"two (callers|threads|requests)|simultaneous")),
    ("blocks_all_requests", re.compile(
        r"blocks? (every|all) (mutating )?(route|request|endpoint|"
        r"call)"), None),
]


def executable_claim(f):
    """Heuristic audit classifier over title + evidence text."""
    text = " ".join(((f.get("title") or "") + " "
                     + (f.get("evidence") or "")).lower().split())
    for name, rx_a, rx_b in EXEC_PAIR_RULES:
        if rx_a.search(text) and (rx_b is None or rx_b.search(text)):
            return True, name
    for name, rx in EXEC_PATTERNS:
        if rx.search(text):
            return True, name
    for name, rx in NONEXEC_PATTERNS:
        if rx.search(text):
            return False, name
    return False, "vague_or_advisory"


def a5_scope(findings_with_case):
    rows = []
    for case_id, f in findings_with_case:
        ex, why = executable_claim(f)
        rows.append({"case_id": case_id, "finding_id": f.get("id"),
                     "title": f.get("title"),
                     "severity_recorded": f.get("severity"),
                     "executable": ex, "basis": why})
    n = len(rows)
    k = sum(1 for r in rows if r["executable"])
    return {"n": n, "executable": k, "pct_executable": pct(k, n),
            "rows": rows}


def run_a5():
    scope_i = [(r["case_id"], f) for r in ATT_EXPANDED
               for f in r["findings"]
               if is_blocking(f.get("severity"))]
    defect_recs = HOLDOUT_DEFECT + PUB_DEFECT
    scope_ii = [(r["case_id"], f) for r in defect_recs
                for f in r["findings"]
                if is_blocking(f.get("severity"))]
    si = a5_scope(scope_i)
    sii = a5_scope(scope_ii)
    n = si["n"] + sii["n"]
    k = si["executable"] + sii["executable"]
    ex_ex = [dict(r, scope="i_expanded_clean_blocking")
             for r in (si["rows"] + sii["rows"]) if r["executable"]][:8]
    # rebuild examples with scope tags properly
    tagged = ([dict(r, scope="i_expanded_clean_blocking")
               for r in si["rows"]]
              + [dict(r, scope="ii_defect_cases_blocking")
                 for r in sii["rows"]])
    examples = {
        "executable": [{kk: r[kk] for kk in (
            "case_id", "finding_id", "title", "basis", "scope")}
            for r in tagged if r["executable"]][:8],
        "not_executable": [{kk: r[kk] for kk in (
            "case_id", "finding_id", "title", "basis", "scope")}
            for r in tagged if not r["executable"]][:8],
    }
    return {
        "analysis": "A5 probe feasibility",
        "classifier": ("HEURISTIC AUDIT — transparent rule-based "
                       "classifier over title+evidence text "
                       "(analysis_sweep.py EXEC_PATTERNS, first "
                       "match wins). Not a ground-truth judgement: "
                       "it estimates what share of blocking claims "
                       "assert a concrete, falsifiable behaviour a "
                       "probe could test."),
        "scope_i_expanded_clean_blocking_recorded": {
            k2: si[k2] for k2 in ("n", "executable", "pct_executable")},
        "scope_ii_defect_cases_blocking_recorded": {
            k2: sii[k2] for k2 in ("n", "executable", "pct_executable")},
        "combined": {"n": n, "executable": k,
                     "pct_executable": pct(k, n)},
        "examples": examples,
        "scope_i_rows": si["rows"],
        "scope_ii_rows": sii["rows"],
    }


# ---------------------------------------------------------------- main

def main():
    a2 = run_a2()
    a3 = run_a3()
    a4 = run_a4()
    a5 = run_a5()
    for name, obj in (("a2-corroboration.json", a2),
                      ("a3-rule-sweep.json", a3),
                      ("a4-seat-emission.json", a4),
                      ("a5-probe-feasibility.json", a5)):
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
    sc = a3["sanity_checks"]
    checks_ok = all([sc["R0_expanded_clean_expected_32/34"],
                     sc["R1_expanded_clean_expected_22/34"],
                     sc["R0_a5_recall_is_1.000"],
                     sc["R1_a5_recall_is_1.000"],
                     sc["R0_public_recall_is_1.000"]])
    summary = {
        "analysis": "B2 Step-1 A2-A5 headline summary (2026-11-05)",
        "sanity_checks": sc,
        "sanity_checks_all_pass": checks_ok,
        "A2": {
            "combined_pct_TP_blocking_E01":
                a2["decision_numbers"]
                ["combined_pct_TP_findings_blocking_E01"],
            "combined_pct_defects_surviving":
                a2["decision_numbers"]["combined_pct_defects_surviving"],
            "combined_pct_cases_ALL_BLOCKING_TP_E01":
                a2["combined"]["case_level"]["pct_ALL_BLOCKING_TP_E01"],
        },
        "A3": {rule: {
            "combined_recall":
                a3["rules"][rule]["combined_defects"]["recall"],
            "combined_precision":
                a3["rules"][rule]["combined_defects"]
                ["merged_blocking_precision"],
            "combined_clean_rate":
                a3["rules"][rule]["clean_blocked"]["combined_clean"]
                ["rate"],
            "J_combined": a3["rules"][rule]["bundles"]["combined"]["J"],
            "shortlist_combined_pass":
                a3["rules"][rule]["shortlist_combined_pass"],
        } for rule in ("R0", "R1", "R2", "R3")},
        "A3_R4": a3["rules"]["R4"],
        "A4_headline": {
            "clean_combined_majors_per_case": {
                s: a4["clean_cases"]["combined"]["seats"][s]
                ["majors_per_case"] for s in SEATS},
            "defect_combined_majors_per_case": {
                s: a4["defect_cases"]["combined"]["seats"][s]
                ["majors_per_case"] for s in SEATS},
        },
        "A5": {
            "scope_i_pct_executable":
                a5["scope_i_expanded_clean_blocking_recorded"]
                ["pct_executable"],
            "scope_ii_pct_executable":
                a5["scope_ii_defect_cases_blocking_recorded"]
                ["pct_executable"],
            "combined_pct_executable": a5["combined"]["pct_executable"],
            "combined_counts": a5["combined"],
        },
    }
    with open(os.path.join(HERE, "a2345-summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    print("SANITY_ALL_PASS:", checks_ok)
    return 0 if checks_ok else 3


if __name__ == "__main__":
    sys.exit(main())
