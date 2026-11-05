"""Benchmark harness (Epic A): run review configurations over a
labelled corpus and score them against ground truth.

The corpus is data, not code: a directory of cases, each a folder
holding `case.json` (metadata + ground-truth expected findings) and
`diff.patch` (the change under review). A *configuration* is a named
panel (provider specs and/or scripted replay seats) described by a
small JSON file, e.g. bench/configs/*.json.

Scoring definitions (kept precise on purpose — these numbers are
the product's public proof):

- A reported finding *matches* an expected defect when they name
  the same file AND either their line numbers are within
  LINE_TOLERANCE, or (when lines are missing or far apart) the
  finding's title shares enough word tokens with the expected
  defect's title/keywords (Jaccard >= TOKEN_OVERLAP_MIN). Severity
  and category are NOT required to match for a match — ground truth
  is severity + location, per the benchmark spec — but a category
  mismatch is recorded on the match.
- Each expected defect is matched by at most one finding, and each
  finding matches at most one expected defect (greedy, worst
  finding severity first, then confidence).
- recall = matched defects / total expected defects.
- A defect *escapes* when no matching finding carries a
  gate-blocking severity (blocker or major — the default gate's
  blocking set): the change would have shipped with the defect,
  either because nobody saw it or because it was only noted as a
  minor/nit. escaped_defect_rate = escaped / total expected.
- precision = matched findings / all reported findings.
- false positives = reported findings matching no expected defect.
  On clean cases (no expected defects) every finding is a false
  positive; clean_fp_rate = clean cases with >= 1 finding / clean
  cases.
- cost per verdict = summed seat cost (attempts x the config's
  cost_per_call_usd) / cases run. Latency is wall time per case;
  p50/p95 use the nearest-rank method.

Scripted seats (`{"name": ..., "script": "file.json"}` in a config)
replay canned reviewer responses keyed by case id. They exist so
the harness and scoring run deterministically in CI with zero
provider calls; their scores validate the harness, not any model.
Real configurations name ordinary provider specs and go through
providers.build_providers like any other run.

The holdout split is private: `build_report(..., public_only=True)`
drops every holdout record before scoring, so holdout case ids,
titles, and per-case rows never appear in a public report.

Runs are resumable: results append to <out>/<config>.jsonl, and a
(config, case) pair already recorded is skipped unless forced.
Stored records are re-validated on resume against the current
corpus and config (diff hash + config hash); stale ones are
dropped and the file rewritten, never silently scored.
"""

import hashlib
import json
import os
import re
import time

from . import core
from . import providers as providers_mod

CASE_SCHEMA = "codereview.benchcase/1"
RESULT_SCHEMA = "codereview.benchresult/1"
REPORT_SCHEMA = "codereview.benchreport/1"

SPLITS = ("public", "holdout")
BLOCKING_SEVERITIES = ("blocker", "major")
LINE_TOLERANCE = 3
TOKEN_OVERLAP_MIN = 0.3

_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ------------------------------------------------------------------ corpus

def _validate_expected(case_id, exp, where):
    if not isinstance(exp, dict):
        raise ValueError(f"{where}: case {case_id}: expected entry "
                         f"is not an object")
    sev = str(exp.get("severity") or "").lower()
    if sev not in core.SEVERITIES:
        raise ValueError(f"{where}: case {case_id}: expected severity "
                         f"{sev!r} not in {core.SEVERITIES}")
    if not str(exp.get("file") or "").strip():
        raise ValueError(f"{where}: case {case_id}: expected entry "
                         f"needs a file")
    if not str(exp.get("title") or "").strip():
        raise ValueError(f"{where}: case {case_id}: expected entry "
                         f"needs a title")
    line = exp.get("line")
    if line is not None:
        try:
            line = int(line)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: case {case_id}: expected line "
                             f"{line!r} is not an integer")
    return {
        "severity": sev,
        "category": str(exp.get("category") or "correctness").lower(),
        "file": str(exp["file"]).strip(),
        "line": line,
        "title": str(exp["title"]).strip(),
        "keywords": [str(k).lower() for k in exp.get("keywords") or []],
    }


def load_case(case_dir):
    """Load and validate one corpus case directory."""
    meta_path = os.path.join(case_dir, "case.json")
    diff_path = os.path.join(case_dir, "diff.patch")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    where = meta_path
    case_id = str(meta.get("id") or "")
    if not _CASE_ID_RE.match(case_id):
        raise ValueError(f"{where}: id {case_id!r} must be lowercase "
                         f"letters, digits, and hyphens")
    if os.path.basename(os.path.normpath(case_dir)) != case_id:
        raise ValueError(f"{where}: directory name must equal the "
                         f"case id {case_id!r}")
    for field in ("title", "category", "source", "license"):
        if not str(meta.get(field) or "").strip():
            raise ValueError(f"{where}: case {case_id}: missing "
                             f"{field}")
    split = str(meta.get("split") or "")
    if split not in SPLITS:
        raise ValueError(f"{where}: case {case_id}: split must be "
                         f"one of {SPLITS}")
    if not os.path.isfile(diff_path):
        raise ValueError(f"{where}: case {case_id}: diff.patch "
                         f"missing")
    with open(diff_path, encoding="utf-8", errors="replace") as fh:
        diff = fh.read()
    if not diff.strip():
        raise ValueError(f"{where}: case {case_id}: diff.patch is "
                         f"empty")
    expected = [_validate_expected(case_id, e, where)
                for e in meta.get("expected") or []]
    return {
        "id": case_id,
        "title": str(meta["title"]).strip(),
        "category": str(meta["category"]).strip(),
        "split": split,
        "source": str(meta["source"]).strip(),
        "license": str(meta["license"]).strip(),
        "context": str(meta.get("context") or ""),
        "expected": expected,
        "diff": diff,
        "dir": case_dir,
    }


def load_corpus(corpus_dir):
    """Load every case under corpus_dir (one subdirectory per case).

    When a manifest.json is present its case list must agree with
    the directories on disk — a case nobody listed, or a listed case
    that is missing, is a loud error, never a silent skip."""
    if not os.path.isdir(corpus_dir):
        raise ValueError(f"corpus directory not found: {corpus_dir}")
    ids = sorted(d for d in os.listdir(corpus_dir)
                 if os.path.isdir(os.path.join(corpus_dir, d))
                 and os.path.isfile(os.path.join(corpus_dir, d,
                                                 "case.json")))
    cases = []
    seen = set()
    for cid in ids:
        case = load_case(os.path.join(corpus_dir, cid))
        if case["id"] in seen:
            raise ValueError(f"duplicate corpus case id {case['id']}")
        seen.add(case["id"])
        cases.append(case)
    manifest_path = os.path.join(corpus_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        listed = sorted(str(c.get("id") or "")
                        for c in manifest.get("cases") or [])
        if listed != sorted(seen):
            raise ValueError(
                f"manifest {manifest_path} disagrees with the case "
                f"directories (manifest-only: "
                f"{sorted(set(listed) - seen)}, dir-only: "
                f"{sorted(seen - set(listed))})")
    return cases


# ------------------------------------------------------------------ scoring

def _tokens(text):
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _finding_matches(exp, finding):
    """(matches, category_match) per the definitions in the module
    docstring."""
    if (finding.get("file") or "").strip().lstrip("./") != \
            exp["file"].lstrip("./"):
        return False, False
    category_match = (finding.get("category") or "").lower() == \
        exp["category"]
    eline, fline = exp.get("line"), finding.get("line")
    if eline is not None and fline is not None and \
            abs(int(fline) - int(eline)) <= LINE_TOLERANCE:
        return True, category_match
    exp_tokens = _tokens(exp["title"]) | set(exp["keywords"])
    fin_tokens = _tokens(finding.get("title"))
    if exp_tokens and fin_tokens:
        overlap = len(exp_tokens & fin_tokens) / \
            len(exp_tokens | fin_tokens)
        if overlap >= TOKEN_OVERLAP_MIN:
            return True, category_match
    return False, category_match


def score_case(case, findings):
    """Score one case's reported findings against its ground truth.

    Returns counts and per-defect detail; findings are the merged
    report findings exactly as the gate saw them (deterministic scan
    findings included — the bench measures the whole pipeline)."""
    findings = list(findings or [])
    order = sorted(
        range(len(findings)),
        key=lambda i: (core._SEV_RANK.get(findings[i].get("severity"),
                                          len(core.SEVERITIES)),
                       -float(findings[i].get("confidence") or 0)))
    used = set()
    defect_rows = []
    matched_findings = 0
    for exp in sorted(case["expected"],
                      key=lambda e: core._SEV_RANK[e["severity"]]):
        hit = None
        for i in order:
            if i in used:
                continue
            ok, cat_ok = _finding_matches(exp, findings[i])
            if ok:
                hit = (i, cat_ok)
                break
        if hit is None:
            defect_rows.append({
                "expected": exp, "matched": False, "escaped": True,
                "finding_severity": None, "category_match": None})
        else:
            i, cat_ok = hit
            used.add(i)
            matched_findings += 1
            sev = findings[i].get("severity")
            defect_rows.append({
                "expected": exp, "matched": True,
                "escaped": sev not in BLOCKING_SEVERITIES,
                "finding_severity": sev, "category_match": cat_ok})
    unmatched = [findings[i] for i in range(len(findings))
                 if i not in used]
    return {
        "expected_total": len(case["expected"]),
        "matched": sum(1 for r in defect_rows if r["matched"]),
        "escaped": sum(1 for r in defect_rows if r["escaped"]),
        "findings_total": len(findings),
        "matched_findings": matched_findings,
        "false_positives": len(unmatched),
        "defects": defect_rows,
    }


def percentile(values, pct):
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    vals = sorted(values)
    rank = max(1, -(-len(vals) * pct // 100))
    return vals[min(rank, len(vals)) - 1]


def aggregate_scores(case_scores):
    """Aggregate per-case score dicts into config-level metrics."""
    total_expected = sum(s["expected_total"] for s in case_scores)
    matched = sum(s["matched"] for s in case_scores)
    escaped = sum(s["escaped"] for s in case_scores)
    total_findings = sum(s["findings_total"] for s in case_scores)
    matched_findings = sum(s["matched_findings"] for s in case_scores)
    clean = [s for s in case_scores if s["expected_total"] == 0]
    return {
        "expected_defects": total_expected,
        "matched_defects": matched,
        "escaped_defects": escaped,
        "recall": (matched / total_expected) if total_expected else None,
        "escaped_defect_rate": (escaped / total_expected)
        if total_expected else None,
        "findings_total": total_findings,
        "false_positives": total_findings - matched_findings,
        "precision": (matched_findings / total_findings)
        if total_findings else None,
        "clean_cases": len(clean),
        "clean_cases_with_fp": sum(1 for s in clean
                                   if s["false_positives"] > 0),
        "clean_fp_rate": (sum(1 for s in clean
                              if s["false_positives"] > 0) / len(clean))
        if clean else None,
    }


# ------------------------------------------------------------------ configs

def resolve_config_path(spec, corpus_dir=None):
    """A config spec is a path to a JSON file, or a name resolved
    against <corpus>/../configs/<name>.json, then ./bench/configs."""
    if os.path.isfile(spec):
        return spec
    name = spec if spec.endswith(".json") else spec + ".json"
    candidates = []
    if corpus_dir:
        candidates.append(os.path.join(corpus_dir, os.pardir,
                                       "configs", name))
    candidates.append(os.path.join("bench", "configs", name))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    raise ValueError(f"bench config not found: {spec!r} (tried "
                     f"{', '.join(candidates) or 'no candidates'})")


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    name = str(cfg.get("name") or
               os.path.splitext(os.path.basename(path))[0])
    if not cfg.get("providers"):
        raise ValueError(f"bench config {path}: 'providers' must be "
                         f"a non-empty list")
    # S1 (void solution §6): the panel's seat->lens binding is
    # EXPLICIT. A config may declare `seat_lenses`; when it does
    # not, the binding is derived ONCE here from the provider
    # order (the historical assignment rule), recorded on the
    # loaded config, and treated as explicit thereafter — so a
    # seat dropped before a run leaves its lens unserved instead
    # of silently remapping lenses onto the survivors. Provider
    # entries may be spec strings or {name, script} objects; the
    # binding keys the SEAT NAMES those entries produce.
    if cfg.get("seat_lenses"):
        seat_lenses = core.normalize_seat_lenses(cfg["seat_lenses"])
        seat_lenses_source = "explicit"
    else:
        seat_lenses = core.derive_seat_lenses(
            _provider_seat_names(cfg["providers"]))
        seat_lenses_source = "derived"
    return {
        "name": name,
        "providers": cfg["providers"],
        "seat_meta": cfg.get("seat_meta") or {},
        "allow_major": bool(cfg.get("allow_major", False)),
        "strict": bool(cfg.get("strict", False)),
        "cost_per_call_usd": cfg.get("cost_per_call_usd") or 0,
        "seat_lenses": seat_lenses,
        "seat_lenses_source": seat_lenses_source,
        "path": path,
    }


def _provider_seat_names(providers):
    """Seat names a config's provider entries produce: a spec
    string names its seat; a {name, script} object names its
    scripted seat (default "scripted", as build_config_providers
    has it)."""
    names = []
    for entry in providers or []:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            names.append(str(entry.get("name") or "scripted"))
        else:
            names.append(str(entry))
    return names


def _config_sha(cfg):
    """Identity hash of a loaded bench config (the file path is
    excluded — the same config at a different location is the same
    config). Stored on every result record; on resume, records
    whose config hash differs are stale and are dropped."""
    identity = {k: cfg.get(k) for k in (
        "name", "providers", "seat_meta", "allow_major", "strict",
        "cost_per_call_usd")}
    # S1: an EXPLICIT seat_lenses binding is part of the config's
    # identity (two panels with the same providers but different
    # bindings are different panels). A DERIVED binding is a pure
    # function of `providers`, which is already in the identity —
    # including it would move the hash of every pre-S1 config and
    # orphan its stored records, so it stays out.
    if cfg.get("seat_lenses_source") == "explicit":
        identity["seat_lenses"] = cfg.get("seat_lenses")
    return hashlib.sha256(json.dumps(
        identity, sort_keys=True).encode("utf-8")).hexdigest()


_CASE_MARKER_RE = re.compile(r"\[bench-case:\s*([a-z0-9-]+)\]")


def _scripted_seat(script_path):
    """A replay seat: canned responses keyed by case id.

    Script format: {"<case-id>": <response object>, "default":
    <response object>}; a case entry may instead be {"by_lens":
    {"correctness": <response>, "operations": <response>}}. The
    response object is the reviewer's normal {"verdict", "summary",
    "findings"} JSON. This is a harness-validation device — it is
    never a model measurement."""
    with open(script_path, encoding="utf-8") as fh:
        script = json.load(fh)

    def seat(prompt):
        m = _CASE_MARKER_RE.search(prompt or "")
        entry = None
        if m:
            entry = script.get(m.group(1))
        if entry is None:
            entry = script.get("default") or {"findings": []}
        if isinstance(entry, dict) and "by_lens" in entry:
            lens = "correctness" if "CORRECTNESS" in (prompt or "") \
                else "operations"
            entry = entry["by_lens"].get(lens) or \
                entry["by_lens"].get("default") or {"findings": []}
        return json.dumps(entry)

    seat.__name__ = "scripted"
    return seat


def build_config_providers(cfg):
    """Config providers -> {seat name: callable} for run_review.

    String entries are ordinary provider specs (built through
    providers.build_providers so presets, custom endpoints, agent
    seats, and account pools all work). Object entries with a
    "script" key build a scripted replay seat; script paths resolve
    relative to the config file."""
    specs = []
    seats = {}
    for entry in cfg["providers"]:
        if isinstance(entry, str):
            specs.append(entry)
        elif isinstance(entry, dict) and entry.get("script"):
            name = str(entry.get("name") or "scripted")
            if name in seats:
                raise ValueError(f"bench config {cfg['name']}: "
                                 f"duplicate scripted seat {name!r}")
            script_path = entry["script"]
            if not os.path.isabs(script_path):
                script_path = os.path.join(
                    os.path.dirname(os.path.abspath(cfg["path"])),
                    script_path)
            seats[name] = _scripted_seat(script_path)
        else:
            raise ValueError(f"bench config {cfg['name']}: provider "
                             f"entry must be a spec string or a "
                             f"{{name, script}} object: {entry!r}")
    if specs:
        built = providers_mod.build_providers(specs)
        for name, fn in built.items():
            if name in seats:
                raise ValueError(f"bench config {cfg['name']}: seat "
                                 f"name {name!r} used by both a "
                                 f"scripted seat and a provider spec")
            seats[name] = fn
    return seats


def _seat_cost(cfg, seat_name):
    rate = cfg["cost_per_call_usd"]
    if isinstance(rate, dict):
        return float(rate.get(seat_name, rate.get("default", 0)) or 0)
    return float(rate or 0)


# ------------------------------------------------------------------ runner

def _read_results(path):
    records = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def run_bench(corpus_dir, config_specs, out_dir, split="all",
              force=False, providers_by_config=None):
    """Run each config over the corpus; append per-case records to
    <out_dir>/<config>.jsonl. Returns {config name: [records]} with
    ALL records on disk (including ones from earlier runs), so a
    resumed run reports the full picture. `providers_by_config`
    lets an embedding runner (e.g. the internal swarm runner) inject
    prebuilt provider callables per config name."""
    if split not in ("all",) + SPLITS:
        raise ValueError(f"split must be all, public, or holdout")
    all_cases = load_corpus(corpus_dir)
    # Hash of every case's diff, across all splits: a stored result
    # record is only a valid resume point when the case it was
    # produced for still exists with the SAME diff (its recorded
    # patch_sha256 is the hash of the diff that was reviewed) and
    # the config that produced it is unchanged. Anything else is
    # stale — trusting it would score findings gathered against a
    # different change or a different panel (review-v11 finding).
    diff_shas = {c["id"]: hashlib.sha256(
        c["diff"].encode("utf-8")).hexdigest() for c in all_cases}
    cases = all_cases
    if split != "all":
        cases = [c for c in cases if c["split"] == split]
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    for spec in config_specs:
        cfg = load_config(resolve_config_path(spec, corpus_dir))
        if providers_by_config and cfg["name"] in providers_by_config:
            seats = providers_by_config[cfg["name"]]
        else:
            seats = build_config_providers(cfg)
        # S1: the config binding governs when the seats actually
        # serving are the config's own seats (a subset is fine —
        # a dropped seat is exactly the case the binding exists
        # for). An embedding runner may inject seats under names
        # the config never declared; a DERIVED binding then falls
        # back to the seat-order rule over the actual seats (the
        # pre-S1 behaviour for that mechanism), while an EXPLICIT
        # binding the runner cannot honour is a loud error, never
        # a silent remap.
        seat_lenses = cfg["seat_lenses"]
        if not set(seats) <= set(_provider_seat_names(
                cfg["providers"])):
            if cfg["seat_lenses_source"] == "explicit":
                raise ValueError(
                    f"bench config {cfg['name']}: explicit "
                    f"seat_lenses binding names "
                    f"{sorted(cfg['seat_lenses'])} but the runner "
                    f"provided seats {sorted(seats)} — refusing "
                    f"to remap lenses silently")
            seat_lenses = core.derive_seat_lenses(list(seats))
        path = os.path.join(out_dir, f"{cfg['name']}.jsonl")
        cfg_sha = _config_sha(cfg)
        records = []
        if not force:
            stale = 0
            for r in _read_results(path):
                if r.get("patch_sha256") == diff_shas.get(
                        r.get("case_id")) \
                        and r.get("config_sha256") == cfg_sha:
                    records.append(r)
                else:
                    stale += 1
            if stale:
                # Rewrite without the stale records so `bench
                # report` never scores results produced for a
                # different corpus or config than the current one.
                with open(path, "w", encoding="utf-8") as fh:
                    for r in records:
                        fh.write(json.dumps(r) + "\n")
        done = {(r["config"], r["case_id"]) for r in records}
        if force:
            # --force means the stored records are REPLACED, not
            # appended to (appending stacked a duplicate record
            # per (config, case) on every forced rerun —
            # review-v12 finding). The replacements stream to a
            # sibling temp file, swapped in only when this
            # config's run completes: a crash mid-run leaves the
            # previous results file intact instead of a truncated
            # stub (the fix diff's own internal review).
            write_path, write_mode = path + ".tmp", "w"
        else:
            write_path, write_mode = path, "a"
        with open(write_path, write_mode, encoding="utf-8") as fh:
            for case in cases:
                key = (cfg["name"], case["id"])
                if key in done:
                    continue
                context = (f"[bench-case: {case['id']}]\n"
                           f"{case['title']}\n{case['context']}"
                           ).strip()
                started = time.monotonic()
                report = core.run_review(
                    case["diff"], seats, context=context,
                    allow_major=cfg["allow_major"],
                    strict=cfg["strict"],
                    seat_meta=cfg["seat_meta"] or None,
                    seat_lenses=seat_lenses)
                duration_ms = int((time.monotonic() - started) * 1000)
                calls = 0
                cost = 0.0
                for rep in report["reviewer_reports"]:
                    attempts = int(rep.get("attempts") or 1)
                    calls += attempts
                    cost += attempts * _seat_cost(cfg,
                                                  rep["provider"])
                record = {
                    "schema": RESULT_SCHEMA,
                    "config": cfg["name"],
                    "config_sha256": cfg_sha,
                    "seat_lenses": report.get("seat_lenses"),
                    "case_id": case["id"],
                    "split": case["split"],
                    "category": case["category"],
                    "created_at": core._now_iso(),
                    "gate": report["gate"],
                    "degraded": report["degraded"],
                    "duration_ms": duration_ms,
                    "calls": calls,
                    "cost_usd": round(cost, 6),
                    "patch_sha256": report["patch_sha256"],
                    "findings": report["findings"],
                    # Shared persisted form (core
                    # .reviewer_report_entry): errored reports
                    # keep their full error string, HTTP status,
                    # failure classes, duration and prompt size —
                    # trimming them here is what made the voided
                    # confirmation attempts' failure classes
                    # unrecoverable (void forensics rec. 3).
                    "reviewer_reports": [
                        core.reviewer_report_entry(r)
                        for r in report["reviewer_reports"]],
                }
                fh.write(json.dumps(record) + "\n")
                fh.flush()
                records.append(record)
                done.add(key)
        if force:
            # The swap is earned by a HEALTHY run only: run_review
            # absorbs provider failures into degraded records
            # instead of raising, so a force run made while a
            # provider is down would otherwise replace good stored
            # results with all-degraded ones (review-v14 finding
            # [2] — the crash leg was already safe: an exception
            # mid-run never reaches this line and the previous file
            # stays intact). Refuse the swap, drop the temp file,
            # and say so loudly; the operator re-runs when the
            # providers are back.
            degraded = [r for r in records if r.get("degraded")]
            if degraded:
                try:
                    os.remove(write_path)
                except OSError:
                    pass
                raise ValueError(
                    f"bench --force: {len(degraded)} of "
                    f"{len(records)} case(s) for config "
                    f"{cfg['name']!r} came back degraded (a "
                    "provider failed); the previous results file "
                    "was left intact — re-run when the providers "
                    "are healthy")
            os.replace(write_path, path)
        results[cfg["name"]] = records
    return results


# ------------------------------------------------------------------ report

def load_results(results_dir):
    """All bench result records in a directory, keyed by config."""
    out = {}
    if not os.path.isdir(results_dir):
        raise ValueError(f"results directory not found: {results_dir}")
    for name in sorted(os.listdir(results_dir)):
        if name.endswith(".jsonl"):
            for rec in _read_results(os.path.join(results_dir, name)):
                out.setdefault(rec["config"], []).append(rec)
    return out


def build_report(results, corpus_dir, public_only=False):
    """Score result records against the corpus ground truth.

    With public_only=True every holdout record is dropped BEFORE
    scoring: no holdout id, title, or row can appear in the report
    (Epic A5 — the holdout split is the overfit guard)."""
    cases = {c["id"]: c for c in load_corpus(corpus_dir)}
    case_shas = {cid: hashlib.sha256(
        c["diff"].encode("utf-8")).hexdigest()
        for cid, c in cases.items()}
    # Current config hashes, when the config file is resolvable:
    # a standalone `bench report` must apply the same config
    # staleness rule as a resumed run, or results produced under
    # an older config get scored as if they were current.
    cfg_shas = {}
    for name in results:
        try:
            cfg_shas[name] = _config_sha(load_config(
                resolve_config_path(name, corpus_dir)))
        except Exception:  # noqa: BLE001 — unresolvable: unjudged
            cfg_shas[name] = None
    stale_dropped = 0
    configs = {}
    for name, records in sorted(results.items()):
        rows = []
        scores = []
        latencies = []
        total_cost = 0.0
        gates = {}
        degraded = 0
        for rec in records:
            case = cases.get(rec["case_id"])
            if case is None:
                raise ValueError(
                    f"result references unknown corpus case "
                    f"{rec['case_id']!r}")
            if public_only and case["split"] == "holdout":
                continue
            if rec.get("patch_sha256") is not None \
                    and rec.get("patch_sha256") != case_shas[case["id"]]:
                # The record was produced for a different diff
                # than the case's current one; scoring it would
                # grade findings against the wrong change.
                stale_dropped += 1
                continue
            if rec.get("config_sha256") is not None \
                    and cfg_shas.get(name) is not None \
                    and rec.get("config_sha256") != cfg_shas[name]:
                # Same rule for the producing config: results
                # gathered under a different panel definition are
                # not this config's results.
                stale_dropped += 1
                continue
            scored = score_case(case, rec.get("findings"))
            scores.append(scored)
            latencies.append(int(rec.get("duration_ms") or 0))
            total_cost += float(rec.get("cost_usd") or 0)
            gates[rec.get("gate")] = gates.get(rec.get("gate"), 0) + 1
            degraded += 1 if rec.get("degraded") else 0
            rows.append({
                "case_id": case["id"],
                "split": case["split"],
                "category": case["category"],
                "gate": rec.get("gate"),
                "degraded": bool(rec.get("degraded")),
                "duration_ms": int(rec.get("duration_ms") or 0),
                "matched": scored["matched"],
                "expected": scored["expected_total"],
                "escaped": scored["escaped"],
                "false_positives": scored["false_positives"],
            })
        metrics = aggregate_scores(scores)
        metrics.update({
            "cases_run": len(rows),
            "defect_cases": sum(1 for r in rows if r["expected"] > 0),
            "gates": gates,
            "degraded_cases": degraded,
            "total_cost_usd": round(total_cost, 6),
            "cost_per_verdict_usd": (round(total_cost / len(rows), 6)
                                     if rows else None),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        })
        configs[name] = {"metrics": metrics, "cases": rows}
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": core._now_iso(),
        "public_only": bool(public_only),
        "holdout_excluded": bool(public_only),
        "corpus_cases": len(cases),
        "stale_records_dropped": stale_dropped,
        "configs": configs,
    }


def _fmt(value, spec="{:.3f}"):
    return "—" if value is None else spec.format(value)


def render_markdown(report):
    lines = ["# CodeReview benchmark report", ""]
    lines.append(f"Generated: {report['generated_at']} · "
                 f"corpus cases known: {report['corpus_cases']}")
    if report["public_only"]:
        lines.append("**Public report — holdout split excluded.** "
                     "Holdout cases are the overfit guard; their "
                     "ids, rows, and scores never appear here.")
    lines.append("")
    lines.append("| Config | Cases | Recall | Escaped-defect rate "
                 "| Precision | Clean-case FP rate | Cost/verdict "
                 "| p50 | p95 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, entry in report["configs"].items():
        m = entry["metrics"]
        lines.append(
            f"| {name} | {m['cases_run']} "
            f"| {_fmt(m['recall'])} "
            f"| {_fmt(m['escaped_defect_rate'])} "
            f"| {_fmt(m['precision'])} "
            f"| {_fmt(m['clean_fp_rate'])} "
            f"| {_fmt(m['cost_per_verdict_usd'], '${:.4f}')} "
            f"| {_fmt(m['latency_p50_ms'], '{:.0f} ms')} "
            f"| {_fmt(m['latency_p95_ms'], '{:.0f} ms')} |")
    for name, entry in report["configs"].items():
        m = entry["metrics"]
        lines += ["", f"## {name}", "",
                  f"Defects: {m['matched_defects']}/"
                  f"{m['expected_defects']} matched, "
                  f"{m['escaped_defects']} escaped · findings: "
                  f"{m['findings_total']} ({m['false_positives']} "
                  f"false positives) · gates: "
                  f"{json.dumps(m['gates'], sort_keys=True)} · "
                  f"degraded cases: {m['degraded_cases']}", "",
                  "| Case | Split | Category | Gate | Matched | "
                  "Escaped | FPs | ms |",
                  "|---|---|---|---|---:|---:|---:|---:|"]
        for row in entry["cases"]:
            lines.append(
                f"| {row['case_id']} | {row['split']} "
                f"| {row['category']} | {row['gate']} "
                f"| {row['matched']}/{row['expected']} "
                f"| {row['escaped']} | {row['false_positives']} "
                f"| {row['duration_ms']} |")
    lines.append("")
    return "\n".join(lines)
