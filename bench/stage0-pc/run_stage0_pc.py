#!/usr/bin/env python3
"""Stage-0 P-C persistence falsifier — Spec A + A2 (DEV measurement).

NOT a registered run: no sealing implications, nothing here is
scored under any registration. It re-samples the two correctness
seats of the registered v2 confirmation panel on the cases whose
registered findings P-C would filter, and measures how often each
registered blocking finding recurs in fresh same-seat samples.

Pre-stated design (fixed before the first call; see RUN-LOG.md):

  * Population A (clean): the 22 BLOCKED clean cases of the v2
    confirmation (attempt-1.jsonl, split "expanded-clean", gate
    blocked) and their 32 correctness-seat-raised blocking-tier
    findings (severity blocker/major as stored; raised = a source
    whose source_lenses include "correctness"). The 1 deterministic
    finding is out of scope.
  * Population A2 (defect): the 9 scored holdout cases and their
    17 correctness-seat-raised blocking-tier findings (3 findings
    with no correctness-seat source are out of scope, stated).
  * Sampling: FRESH k=3 samples per (case, correctness seat) —
    31 cases x 2 seats x 3 = 186 sample draws. A sample is the
    product's own reviewer response: core._call_and_parse over a
    cache-free GenerationSeat wrapping the registered transport
    (run_generation_v2.build_transport + PARAMS verbatim), on the
    exact prompt the registered run built (identity-verified by
    prompt hash in phase 0). Findings are normalised with
    core._normalize_finding(raw, seat, lens="correctness") —
    reviewer-level findings, exactly what reviewer_reports store;
    downstream gate machinery (grounding, re-ground, TL) is not
    part of a seat's raise and is not applied. A draw that fails
    (transport exhaustion or unparseable after the product's own
    recovery) is retried with a fresh seat up to 2 more times —
    mirroring the product's persistence in obtaining a response;
    only a draw that fails all attempts is recorded invalid, and
    an invalid draw never counts as non-recurrence.
  * Matching rule: a registered finding F recurs in sample S of
    raising seat X iff some finding in S merges with F under the
    product merger — operationalised literally: core
    .merge_findings([F, S_i]) yields one group. (merge_findings:
    same file + category and title-token Jaccard >= 0.5, or same
    line and title containment >= 0.5.) Severity of the sample
    finding does not gate the primary count (the claim recurred);
    a major-only sensitivity is recorded alongside.
  * A both-seats finding is tested against each raising seat's
    samples; it counts as recurring if it recurs in >=2/3 samples
    of at least one raising seat (either-seat variant); the
    both-seats variant is reported too.
  * Decision rule: rho_clean = share of the 32 findings recurring
    in >=2/3 samples of their raising seat. rho_clean >= 0.70
    (>=23/32) -> P-C DEAD. Otherwise P-C lives; the implied
    clean-BLOCKED at the measured rho uses her case-level formula.
  * Spend: shadow-priced with bench/generation.py's list-price
    table (the registered runs' metering). HARD CAP $1.50 of
    shadow spend: no new sample draw starts once spent + the
    worst-case cost of a draw would exceed the cap.

Phases: identity (0, no provider spend) / prompts / sample / score.
Outputs land in bench/stage0-pc/ (raw/ per-sample records,
identity-check.json, recurrence-table.json, spend.json).
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(WORKTREE, "bench", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, os.path.join(WORKTREE, "bench"))
sys.path.insert(0, "/home/hatch/workspace/mitbbs-ai-swarm/agents")

# Bench DeepSeek seat resolves to the dedicated bench key, as in
# the registered runs (must be set before llm_chain import).
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import generation as gen  # noqa: E402
import run_confirmation_v2 as conf  # noqa: E402
import run_generation_v2 as drv  # noqa: E402
import run_panel_baseline as panel_driver  # noqa: E402
from codereview import bench as bench_mod  # noqa: E402
from codereview import core  # noqa: E402

OUT = HERE
RAW = os.path.join(OUT, "raw")
ATTEMPT1 = os.path.join(WORKTREE, "bench", "generation-v2",
                        "attempt-1.jsonl")
GEN1 = os.path.join(WORKTREE, "bench", "generation-v2",
                    "generation-attempt-1.jsonl")
BINDING = {"openai": ["correctness"], "nvidia": ["operations"],
           "deepseek": ["correctness"]}
CORRECTNESS_SEATS = ("openai", "deepseek")
BLOCKING = ("blocker", "major")
K = 3
CAP_USD = 1.50
# Worst-case shadow cost of one sample draw (gpt-5.4 seat, long
# output + the product's parse-repair redraws): used only for the
# cap projection check before a draw starts.
WORST_DRAW_USD = 0.045
DRAW_ATTEMPTS = 3  # 1 + 2 retries of a failed draw (fresh seat each)


# ------------------------------------------------------------------
# Populations

def corr_seats(f):
    sl = f.get("source_lenses") or {}
    return sorted(s for s, lenses in sl.items()
                  if "correctness" in (lenses or []))


def populations():
    """(clean_targets, defect_targets): {case_id: [finding, ...]}
    with finding = the stored merged record finding (dict)."""
    records = [json.loads(l) for l in open(ATTEMPT1, encoding="utf-8")
               if l.strip()]
    clean, defect = {}, {}
    for rec in records:
        fs = [f for f in rec["findings"]
              if (f.get("severity") or "").lower() in BLOCKING
              and corr_seats(f)]
        if rec["split"] == "expanded-clean" \
                and (rec["gate"] or "").lower() == "blocked":
            clean[rec["case_id"]] = fs
        elif rec["split"] == "holdout":
            defect[rec["case_id"]] = fs
    return clean, defect


def load_cases():
    corpus = bench_mod.load_corpus(drv.CORPUS)
    cases = {c["id"]: c for c in corpus}
    for c in conf.load_expanded_clean():
        cases[c["id"]] = c
    return cases


def bench_context(case):
    return (f"[bench-case: {case['id']}]\n"
            f"{case['title']}\n"
            f"{case.get('context') or ''}").strip()


def capture_prompts(case, cfg):
    """The exact prompts run_review builds for this case, captured
    with spy seats (no provider spend): {seat: [prompt, ...]}."""
    captured = {s: [] for s in BINDING}

    def make_spy(name):
        def spy(prompt):
            captured[name].append(prompt)
            return json.dumps({"summary": "capture", "findings": []})
        return spy

    spies = {n: make_spy(n) for n in BINDING}
    core.run_review(
        case["diff"], spies, context=bench_context(case),
        allow_major=cfg["allow_major"], strict=cfg["strict"],
        seat_meta=cfg["seat_meta"] or None, seat_lenses=BINDING,
        fallbacks={"correctness": ("openai", spies["openai"])},
        gate_profile="balanced")
    return captured


# ------------------------------------------------------------------
# Phase 0: identity verification (spy seats, no provider spend)

def identity_check(case_ids, cases, cfg, log):
    gen_recs = {}
    for line in open(GEN1, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r["status"] == "valid":
                gen_recs[(r["case_id"], r["seat"], r["lens"])] = r
    results, failures = {}, []
    for cid in case_ids:
        captured = capture_prompts(cases[cid], cfg)
        row = {}
        for seat in CORRECTNESS_SEATS:
            prompts = captured[seat]
            stored = gen_recs.get((cid, seat, "correctness"))
            if stored is None:
                failures.append(f"{cid}/{seat}: no valid stored "
                                f"generation record")
                continue
            hashes = [gen.prompt_hash(p) for p in prompts]
            ok = (len(prompts) == 1
                  and hashes[0] in stored["prompt_hashes"]
                  and gen.params_hash(drv.PARAMS[seat])
                  == stored["params_hash"]
                  and panel_driver.MODELS[seat] == stored["model"])
            row[seat] = {"prompts": len(prompts),
                         "prompt_hash": hashes[0] if hashes else None,
                         "stored_hashes": stored["prompt_hashes"],
                         "model": stored["model"], "ok": ok}
            if not ok:
                failures.append(
                    f"{cid}/{seat}: identity mismatch {row[seat]}")
        results[cid] = row
        log(f"identity {cid}: "
            + ", ".join(f"{s}={'ok' if row[s]['ok'] else 'FAIL'}"
                        for s in CORRECTNESS_SEATS))
    return results, failures


# ------------------------------------------------------------------
# Sampling

class Meter:
    def __init__(self):
        self.lock = threading.Lock()
        self.spent = 0.0
        self.calls = 0

    def add(self, usd, calls):
        with self.lock:
            self.spent += usd
            self.calls += calls

    def snapshot(self):
        with self.lock:
            return self.spent

    def may_start(self):
        with self.lock:
            return self.spent + WORST_DRAW_USD <= CAP_USD


def draw_sample(case_id, seat_name, sample_idx, prompt, meter, log):
    """One fresh reviewer sample. Returns a record dict; never
    raises (failures are recorded as invalid draws)."""
    transport = drv.build_transport(seat_name)
    started = time.monotonic()
    status, parsed, err = "ok", None, None
    events, cost, raw_calls = [], 0.0, 0
    for _try in range(DRAW_ATTEMPTS):
        seat = gen.GenerationSeat(
            seat_name, panel_driver.MODELS[seat_name], transport,
            params=drv.PARAMS[seat_name])
        try:
            parsed = core._call_and_parse(seat, prompt)
            err = None
            status = "ok"
        except Exception as exc:  # noqa: BLE001 — recorded
            parsed, status = None, "invalid"
            err = f"{type(exc).__name__}: {exc}"[:300]
        for e in seat.events:
            c, _known = gen.shadow_price(seat.model, e["tokens_in"],
                                         e["tokens_out"])
            cost += c
            if e["outcome"] in ("ok", "content_invalid",
                                "transport_error"):
                raw_calls += 1
        events.extend(seat.events)
        if status == "ok":
            break
    meter.add(cost, raw_calls)
    findings = []
    if parsed is not None:
        for raw_f in parsed.get("findings") or []:
            nf = core._normalize_finding(raw_f, seat_name,
                                         lens="correctness")
            if nf:
                findings.append(nf)
    rec = {"case_id": case_id, "seat": seat_name,
           "sample": sample_idx, "status": status, "error": err,
           "prompt_hash": gen.prompt_hash(prompt),
           "params_hash": gen.params_hash(drv.PARAMS[seat_name]),
           "model": panel_driver.MODELS[seat_name],
           "events": events, "shadow_cost_usd": round(cost, 6),
           "duration_ms": int((time.monotonic() - started) * 1000),
           "findings": findings}
    log(f"sample {case_id}/{seat_name}#{sample_idx}: {status} "
        f"findings={len(findings)} cost=${cost:.4f} "
        f"cum=${meter.snapshot():.4f}")
    return rec


# ------------------------------------------------------------------
# Matching + scoring

def merges(f, s):
    """The product merger's pairwise predicate, applied literally:
    merge_findings([f, s]) collapses to one group."""
    a = dict(f)
    a["sources"] = list(f.get("sources") or [])
    b = dict(s)
    b["sources"] = list(s.get("sources") or [])
    out = core.merge_findings([a, b])
    return len(out) == 1


def score(pop_map, samples):
    """samples: {(case_id, seat): [sample record, ...]}.
    Returns the per-finding recurrence table + rho values."""
    table = []
    for cid, findings in pop_map.items():
        for f in findings:
            seats = corr_seats(f)
            per_seat = {}
            for seat in seats:
                draws = samples.get((cid, seat), [])
                valid = [d for d in draws if d["status"] == "ok"]
                hits = hits_major = 0
                detail = []
                for d in valid:
                    matched = [sf for sf in d["findings"]
                               if merges(f, sf)]
                    if matched:
                        hits += 1
                        if any((sf.get("severity") or "").lower()
                               in BLOCKING for sf in matched):
                            hits_major += 1
                    detail.append({
                        "sample": d["sample"],
                        "matched": len(matched),
                        "matched_titles": [m["title"]
                                           for m in matched]})
                per_seat[seat] = {
                    "valid_samples": len(valid),
                    "recurs_in": hits,
                    "recurs_in_major_only": hits_major,
                    "recurs": hits >= 2,
                    "recurs_major_only": hits_major >= 2,
                    "detail": detail}
            table.append({
                "case_id": cid,
                "file": f.get("file"), "line": f.get("line"),
                "category": f.get("category"),
                "title": f.get("title"),
                "severity": f.get("severity"),
                "raising_seats": seats, "per_seat": per_seat,
                "recurs_either_seat": any(
                    p["recurs"] for p in per_seat.values()),
                "recurs_both_seats": all(
                    p["recurs"] for p in per_seat.values()),
                "recurs_either_seat_major_only": any(
                    p["recurs_major_only"]
                    for p in per_seat.values())})
    n = len(table)
    div = (lambda x: (x / n) if n else None)
    return table, {
        "n": n,
        "recurring": sum(1 for t in table if t["recurs_either_seat"]),
        "rho": div(sum(1 for t in table if t["recurs_either_seat"])),
        "rho_both_seats_variant": div(sum(
            1 for t in table if t["recurs_both_seats"])),
        "rho_major_only_sensitivity": div(sum(
            1 for t in table
            if t["recurs_either_seat_major_only"]))}


def cases_still_blocked(clean_map, clean_table):
    """Case-level simulation: a blocked clean case stays blocked
    under P-C iff at least one of its seat-raised findings recurs
    (the one deterministic-finding case, xc-batch-delete-guarded,
    also carries seat-raised findings, so it is covered here; its
    deterministic finding would keep it blocked regardless — the
    simulation notes it separately in the results)."""
    by_case = {}
    for t in clean_table:
        by_case.setdefault(t["case_id"], []).append(t)
    still = [cid for cid, fs in by_case.items()
             if any(t["recurs_either_seat"] for t in fs)]
    missing = [cid for cid in clean_map if cid not in by_case]
    return sorted(still), sorted(missing)


def main(argv):
    phase = argv[1] if len(argv) > 1 else ""
    os.makedirs(RAW, exist_ok=True)
    log_lock = threading.Lock()

    def log(msg):
        with log_lock:
            print(msg, flush=True)

    cfg = bench_mod.load_config(drv.CONFIG_SPEC)
    clean, defect = populations()
    cases = load_cases()
    n_clean_f = sum(len(v) for v in clean.values())
    n_def_f = sum(len(v) for v in defect.values())
    log(f"populations: clean {len(clean)} cases / {n_clean_f} findings; "
        f"defect {len(defect)} cases / {n_def_f} findings")
    assert n_clean_f == 32, f"clean findings {n_clean_f} != 32"
    assert n_def_f == 17, f"defect findings {n_def_f} != 17"
    case_ids = sorted(set(clean) | set(defect))

    if phase == "identity":
        results, failures = identity_check(case_ids, cases, cfg, log)
        with open(os.path.join(OUT, "identity-check.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"results": results, "failures": failures},
                      fh, indent=1)
        log(f"identity failures: {len(failures)}")
        return 0 if not failures else 3

    if phase == "prompts":
        prompts = {}
        for cid in case_ids:
            captured = capture_prompts(cases[cid], cfg)
            prompts[cid] = {s: captured[s] for s in CORRECTNESS_SEATS}
            assert all(len(prompts[cid][s]) == 1
                       for s in CORRECTNESS_SEATS), cid
        with open(os.path.join(OUT, "prompts.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(prompts, fh, indent=1)
        log(f"prompts captured: {len(prompts)} cases")
        return 0

    if phase == "sample":
        prompts = json.load(open(os.path.join(OUT, "prompts.json"),
                                 encoding="utf-8"))
        meter = Meter()
        jobs = [(cid, seat, i, prompts[cid][seat][0])
                for cid in case_ids for seat in CORRECTNESS_SEATS
                for i in range(1, K + 1)]
        log(f"sample jobs: {len(jobs)}")
        done = []

        def work(job):
            cid, seat, i, prompt = job
            if not meter.may_start():
                rec = {"case_id": cid, "seat": seat, "sample": i,
                       "status": "skipped_cap",
                       "error": "spend cap projection",
                       "findings": [], "shadow_cost_usd": 0.0,
                       "events": []}
            else:
                rec = draw_sample(cid, seat, i, prompt, meter, log)
            path = os.path.join(RAW, f"{cid}--{seat}--{i}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=1)
            done.append(rec)
            return rec

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(work, jobs))
        ok = sum(1 for r in done if r["status"] == "ok")
        log(f"samples done: {ok}/{len(jobs)} ok; "
            f"spend=${meter.snapshot():.4f} raw_calls={meter.calls}")
        with open(os.path.join(OUT, "spend.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"shadow_spent_usd": round(meter.snapshot(), 6),
                       "raw_calls": meter.calls,
                       "samples_ok": ok, "samples_total": len(jobs)},
                      fh, indent=1)
        return 0

    if phase == "score":
        samples = {}
        for fn in sorted(os.listdir(RAW)):
            if fn.endswith(".json"):
                with open(os.path.join(RAW, fn),
                          encoding="utf-8") as fh:
                    rec = json.load(fh)
                samples.setdefault((rec["case_id"], rec["seat"]),
                                   []).append(rec)
        for v in samples.values():
            v.sort(key=lambda r: r["sample"])
        clean_table, clean_rho = score(clean, samples)
        defect_table, defect_rho = score(defect, samples)
        still, missing = cases_still_blocked(clean, clean_table)
        spend = None
        sp = os.path.join(OUT, "spend.json")
        if os.path.isfile(sp):
            with open(sp, encoding="utf-8") as fh:
                spend = json.load(fh)
        out = {"clean": {"rho_block": clean_rho, "table": clean_table,
                         "cases_still_blocked_under_pc": still,
                         "cases_with_no_seat_raised_findings": missing,
                         "blocked_cases_total": len(clean)},
               "defect": {"rho_block": defect_rho,
                          "table": defect_table},
               "spend": spend}
        with open(os.path.join(OUT, "recurrence-table.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        log(json.dumps({"clean_rho": clean_rho,
                        "defect_rho": defect_rho,
                        "cases_still_blocked": still}, indent=1))
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
