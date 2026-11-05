"""Tech Lead acceptance runner (refutation-process solution
§6, owner-adopted 2026-11-04): run the SHADOW Tech Lead over
the known-answer corpus at ~/workspace/codereview-acceptance/
and score the adopted gates M1–M6.

The corpus is the contract: case sets, scoring rules and
thresholds are read from the corpus's scorecard.json, never
hardcoded here. Scoring follows the scorecard's
scored-decision definition — probes are NOT executed (probe
results ship inside the cases and are presented as context);
a needs_probe outcome scores as escalate; a decision whose
deciding quote does not validate scores as escalate (the
shadow draw machinery already enforces that normalization).

The machinery stratum's isolation rule is honoured by
construction: shadow adjudication never consults the
precedent store, and every (case, variant) run uses a fresh
decision cache.
"""

from __future__ import annotations

import json
import os

from . import core


def load_corpus(corpus_dir):
    def read(name):
        with open(os.path.join(corpus_dir, name),
                  encoding="utf-8") as fh:
            return json.load(fh)

    index = read("index.json")
    cases = {}
    for item in index["cases"]:
        cid = item["case_id"]
        cases[cid] = read(os.path.join("cases", f"{cid}.json"))
    return {"index": index, "scorecard": read("scorecard.json"),
            "mutations": read("mutations.json"), "cases": cases}


def _independence(seat_family, raiser_fam, refuter_fam):
    if seat_family in (raiser_fam, refuter_fam, "unknown", None):
        return "reduced"
    return "independent"


def case_inputs(case, seat_family, *, family_swap=False,
                vendor_strip=False, paraphrase=None):
    """Map a corpus case to (finding, dispute, region,
    independence) for shadow_adjudicate, applying the
    requested mutation to the PRESENTED inputs only — quotes
    and the code region are never mutated."""
    f0 = case["finding"]
    r0 = case["refutation"]
    evidence = f0.get("evidence") or f0.get("claim") or ""
    reason = r0.get("reason") or ""
    if paraphrase is not None:
        evidence, reason = paraphrase
    if vendor_strip:
        evidence = core._scrub_vendor(evidence)
        reason = core._scrub_vendor(reason)
    raiser_fam = f0.get("raised_by_family")
    refuter_fam = r0.get("by_family")
    if family_swap:
        raiser_fam, refuter_fam = refuter_fam, raiser_fam
    finding = {
        "id": case["case_id"],
        "file": f0.get("file"), "line": f0.get("line"),
        "severity": f0.get("severity_as_raised"),
        "title": f0.get("claim") or "",
        "evidence": evidence,
        "evidence_quote": f0.get("evidence_quote") or ""}
    dispute = {
        "by": "refuter", "family": refuter_fam,
        "raiser_family": raiser_fam,
        "evidence_quote": r0.get("quote") or "",
        "reason": reason}
    region = (case.get("code_region") or {}).get("text") or ""
    return finding, dispute, region, _independence(
        seat_family, raiser_fam, refuter_fam)


def scored_decision(entry):
    """The scored decision per scorecard.json: the entry's
    final decision, with every non-decision state normalized
    to escalate."""
    decision = (entry or {}).get("decision")
    if decision in ("sustain_finding", "sustain_refutation"):
        return decision
    return "escalate"


def scored_severity(entry):
    return ((entry or {}).get("severity_after_rubric") or {}
            ).get("level")


def score_case(case, entry):
    """Score one baseline entry under the case's own scoring
    rule. Returns {"correct", "false_dismissal",
    "scored_decision"}."""
    expected = case.get("expected") or {}
    rule = expected.get("scoring") or "exact"
    scored = scored_decision(entry)
    out = {"correct": False, "false_dismissal": False,
           "scored_decision": scored, "rule": rule}
    if rule == "dismissal_evidence_rule":
        if scored == "escalate":
            out["correct"] = True
        elif scored == "sustain_refutation":
            quote = ((entry.get("deciding_evidence") or {})
                     .get("quote") or "")
            region = (case.get("code_region") or {}).get(
                "text") or ""
            refuter_quote = (case.get("refutation") or {}).get(
                "quote") or ""
            out["correct"] = bool(
                quote
                and core._quote_grounded(quote, region)
                and core._norm_quote(quote)
                != core._norm_quote(refuter_quote))
        return out
    if rule == "machinery_two_field":
        want = expected.get("decision")
        if want == "refutation_rejected":
            decision_ok = scored == "sustain_finding"
        else:
            decision_ok = scored == want
        validity = expected.get("reasoning_validity") or {}
        assess = entry.get("reasoning_assessment") or {}
        claim_ok = ("true" if assess.get("claim_valid")
                    else "false") == validity.get("claim")
        refutation_ok = assess.get(
            "refutation_validity") == validity.get("refutation")
        out["correct"] = bool(
            decision_ok and claim_ok and refutation_ok)
        out["reasoning_match"] = {
            "claim": claim_ok, "refutation": refutation_ok}
        return out
    # exact
    if scored != expected.get("decision"):
        return out
    want_sev = expected.get("severity_after")
    if want_sev is not None \
            and scored_severity(entry) != want_sev:
        return out
    out["correct"] = True
    return out


_PARAPHRASE_PROMPT = (
    "Paraphrase the following text, preserving every factual "
    "claim and its direction exactly, changing only the "
    "wording. Return ONLY the paraphrased text.\n\n{text}")


def _paraphrase(seat_fn, text, timeout):
    """One paraphrase call through the seat itself (the
    mutation protocol allows an LLM paraphrase under a
    semantics-preserving instruction). Plain-text call — the
    JSON job machinery does not apply; the seat's own
    transport timeout bounds it. A failed paraphrase keeps
    the original text and the case is scored as-is."""
    if not text:
        return text
    try:
        out = seat_fn(_PARAPHRASE_PROMPT.format(text=text[:4000]))
    except Exception:  # noqa: BLE001
        return text
    return str(out).strip() or text


def run_acceptance(corpus_dir, seat_fn, *, seat_family,
                   seat_name="acceptance-tech-lead",
                   do_mutations=True, timeout=180, log=None):
    """Run the full acceptance protocol and return the run
    record: per-case entries and scores, mutation flips, and
    the M1–M6 measurements against the scorecard's own
    thresholds. The unlock verdict requires EVERY gate metric
    to pass on this single run."""
    log = log or (lambda _msg: None)
    corpus = load_corpus(corpus_dir)
    cases = corpus["cases"]
    scorecard = corpus["scorecard"]
    metrics_spec = {m["id"]: m
                    for m in scorecard.get("metrics") or []}

    def adjudicate(case, **kw):
        finding, dispute, region, indep = case_inputs(
            case, seat_family, **kw)
        return core.shadow_adjudicate(
            seat_fn, finding, region, dispute,
            seat_name=seat_name, seat_family=seat_family,
            independence=indep, probe_fn=None,
            probe_context=case.get("probe"), cache={},
            timeout=timeout)

    baseline = {}
    scores = {}
    for cid in sorted(cases):
        entry = adjudicate(cases[cid])
        baseline[cid] = entry
        scores[cid] = score_case(cases[cid], entry)
        log(f"baseline {cid}: {scored_decision(entry)} "
            f"(correct={scores[cid]['correct']})")

    mutation_ids = [m["id"] for m in
                    (corpus["mutations"].get("mutations") or [])]
    flips = {mid: [] for mid in mutation_ids}
    paraphrases = {}
    if do_mutations:
        for cid in sorted(cases):
            case = cases[cid]
            base = (scored_decision(baseline[cid]),
                    scored_severity(baseline[cid]))
            for mid in mutation_ids:
                if mid == "position_swap":
                    # Force the opposite A/B order relative to
                    # the baseline draw for this case.
                    finding, dispute, region, indep = \
                        case_inputs(case, seat_family)
                    entry = core.shadow_adjudicate(
                        seat_fn, finding, region, dispute,
                        seat_name=seat_name,
                        seat_family=seat_family,
                        independence=indep, probe_fn=None,
                        probe_context=case.get("probe"),
                        cache={}, timeout=timeout,
                        force_swap=True)
                elif mid == "family_swap":
                    entry = adjudicate(case, family_swap=True)
                elif mid == "vendor_strip":
                    entry = adjudicate(case, vendor_strip=True)
                elif mid == "reason_paraphrase":
                    pair = (
                        _paraphrase(
                            seat_fn,
                            case["finding"].get("evidence")
                            or case["finding"].get("claim")
                            or "", timeout),
                        _paraphrase(
                            seat_fn,
                            case["refutation"].get("reason")
                            or "", timeout))
                    paraphrases[cid] = {
                        "evidence": pair[0], "reason": pair[1]}
                    entry = adjudicate(case, paraphrase=pair)
                else:
                    continue
                now = (scored_decision(entry),
                       scored_severity(entry))
                if now != base:
                    flips[mid].append(cid)
                log(f"mutation {mid} {cid}: {now[0]} "
                    f"(flip={now != base})")

    def metric_set(mid):
        spec = metrics_spec.get(mid) or {}
        s = spec.get("set")
        if isinstance(s, list):
            return s
        return sorted(cases)

    def threshold(mid):
        spec = metrics_spec.get(mid) or {}
        return spec.get("threshold") or {}

    def passes(value, mid):
        th = threshold(mid)
        op, want = th.get("op"), th.get("value")
        if op == "==":
            return value == want
        if op == ">=":
            return value >= want
        if op == "<=":
            return value <= want
        return False

    # M1: false dismissals on the real-finding set.
    m1_set = metric_set("M1_false_dismissals_on_real_findings")
    m1 = sum(1 for cid in m1_set
             if scored_decision(baseline[cid])
             == "sustain_refutation")
    # M2: accuracy on the probe-settled set.
    m2_set = metric_set("M2_probe_settled_accuracy")
    m2 = (sum(1 for cid in m2_set if scores[cid]["correct"])
          / len(m2_set)) if m2_set else 0.0
    # M3: overall accuracy.
    m3 = sum(1 for c in scores.values() if c["correct"]) \
        / len(scores)
    # M4: mutation flip rate.
    total_flips = sum(len(v) for v in flips.values())
    denom = len(cases) * len(mutation_ids) if do_mutations \
        else 0
    m4 = (total_flips / denom) if denom else None
    # M5: protected + insufficient all escalated.
    m5_set = metric_set(
        "M5_protected_and_insufficient_escalated")
    m5 = (sum(1 for cid in m5_set
              if scored_decision(baseline[cid]) == "escalate")
          / len(m5_set)) if m5_set else 0.0
    # M6: double-draw agreement on majors.
    major_ids = [cid for cid, c in cases.items()
                 if (c["finding"].get("severity_as_raised")
                     in ("blocker", "major"))]
    agreed = [cid for cid in major_ids
              if baseline[cid].get("draws_agree") is True]
    measured = [cid for cid in major_ids
                if baseline[cid].get("draws_agree") is not None]
    m6 = (len(agreed) / len(measured)) if measured else None

    metrics = {
        "M1_false_dismissals_on_real_findings": {
            "measured": m1, "threshold": threshold(
                "M1_false_dismissals_on_real_findings"),
            "pass": passes(
                m1, "M1_false_dismissals_on_real_findings"),
            "set_size": len(m1_set)},
        "M2_probe_settled_accuracy": {
            "measured": m2, "threshold": threshold(
                "M2_probe_settled_accuracy"),
            "pass": passes(m2, "M2_probe_settled_accuracy"),
            "set_size": len(m2_set)},
        "M3_overall_accuracy": {
            "measured": m3,
            "threshold": threshold("M3_overall_accuracy"),
            "pass": passes(m3, "M3_overall_accuracy"),
            "set_size": len(scores)},
        "M4_mutation_flip_rate": {
            "measured": m4,
            "threshold": threshold("M4_mutation_flip_rate"),
            "pass": bool(do_mutations) and passes(
                m4, "M4_mutation_flip_rate"),
            "flips": flips, "denominator": denom},
        "M5_protected_and_insufficient_escalated": {
            "measured": m5, "threshold": threshold(
                "M5_protected_and_insufficient_escalated"),
            "pass": passes(
                m5, "M5_protected_and_insufficient_escalated"),
            "set_size": len(m5_set)},
        "M6_double_draw_agreement_on_majors": {
            "measured": m6, "threshold": threshold(
                "M6_double_draw_agreement_on_majors"),
            "pass": m6 is not None and passes(
                m6, "M6_double_draw_agreement_on_majors"),
            "majors": len(major_ids),
            "measured_cases": len(measured),
            "agreed_cases": len(agreed)},
    }
    unlock = all(m["pass"] for m in metrics.values())
    return {
        "seat_family": seat_family, "seat_name": seat_name,
        "corpus": corpus_dir,
        "protocol_version": core.ADJUDICATION_PROTOCOL_VERSION,
        "rubric_version": core.RUBRIC_VERSION,
        "cases": {cid: {"entry": baseline[cid],
                        "score": scores[cid]}
                  for cid in sorted(cases)},
        "paraphrases": paraphrases,
        "metrics": metrics,
        "unlock_all_gates_pass": unlock}
