#!/usr/bin/env python3
"""Failure-versus-case-feature analysis (void solution §3.2,
selection-bias guard).

Retries driven by transport errors do not bias a measurement
UNLESS the failures correlate with case features. This script
reads generation records (bench/generation.py) and the corpus,
and reports, per case, failure/retry counts against features —
diff size, primary language, defect-or-clean — with the Pearson
correlation for size and the group means for the rest. A strong
correlation is a REPORTING obligation (widen the bounds and say
so), not something to tune away.

Usage:
  analyze_failure_features.py <generation-attempt-N.jsonl>
                              [--corpus DIR] [--expanded DIR]
"""

import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WORKTREE, "src"))

from codereview import bench as bench_mod  # noqa: E402

EXT_LANG = {".py": "python", ".php": "php", ".js": "javascript",
            ".ts": "typescript", ".go": "go", ".java": "java",
            ".rb": "ruby", ".rs": "rust", ".c": "c", ".cpp": "cpp",
            ".sh": "shell", ".sql": "sql"}


def case_features(case):
    diff = case["diff"]
    langs = {}
    for path in re.findall(r"^\+\+\+ b/(.+)$", diff, re.M):
        ext = os.path.splitext(path)[1].lower()
        lang = EXT_LANG.get(ext, "other")
        langs[lang] = langs.get(lang, 0) + 1
    primary = (max(langs, key=langs.get) if langs else "unknown")
    return {"diff_chars": len(diff),
            "diff_lines": diff.count("\n") + 1,
            "files": len(langs) and sum(langs.values()) or 0,
            "language": primary,
            "defect": bool(case.get("expected")),
            "split": case.get("split"),
            "category": case.get("category")}


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def main(argv):
    gen_path = argv[1]
    corpus_dir = os.path.join(WORKTREE, "bench", "corpus")
    if "--corpus" in argv:
        corpus_dir = argv[argv.index("--corpus") + 1]
    cases = {c["id"]: c for c in bench_mod.load_corpus(corpus_dir)}
    if "--expanded" in argv:
        exp = argv[argv.index("--expanded") + 1]
        with open(os.path.join(exp, "manifest.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        for entry in manifest.get("cases") or []:
            cid = str(entry.get("id") or "")
            cdir = os.path.join(exp, cid)
            with open(os.path.join(cdir, "case.json"),
                      encoding="utf-8") as fh:
                meta = json.load(fh)
            with open(os.path.join(cdir, "diff.patch"),
                      encoding="utf-8", errors="replace") as fh:
                diff = fh.read()
            cases[cid] = {"id": cid, "split": "expanded-clean",
                          "category": meta.get("category"),
                          "expected": [], "diff": diff}
    per_case = {}
    with open(gen_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            agg = per_case.setdefault(
                r["case_id"], {"failures": 0, "retries": 0,
                               "attempts": 0, "unscored_seats": 0})
            agg["failures"] += r.get("failure_count") or 0
            agg["retries"] += r.get("retries") or 0
            agg["attempts"] += r.get("attempts") or 0
            if r.get("status") == "unscored_infra":
                agg["unscored_seats"] += 1
    rows = []
    for cid, agg in sorted(per_case.items()):
        case = cases.get(cid)
        if case is None:
            continue
        row = dict(case_features(case), case_id=cid, **agg)
        rows.append(row)
    failures = [r["failures"] for r in rows]
    sizes = [r["diff_chars"] for r in rows]
    defect = [r["failures"] for r in rows if r["defect"]]
    clean = [r["failures"] for r in rows if not r["defect"]]
    by_lang = {}
    for r in rows:
        by_lang.setdefault(r["language"], []).append(r["failures"])

    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    report = {
        "cases": len(rows),
        "total_failures": sum(failures),
        "total_retries": sum(r["retries"] for r in rows),
        "unscored_seat_records": sum(
            r["unscored_seats"] for r in rows),
        "pearson_failures_vs_diff_chars": (
            round(pearson(sizes, failures), 3)
            if pearson(sizes, failures) is not None else None),
        "mean_failures_defect_cases": mean(defect),
        "mean_failures_clean_cases": mean(clean),
        "mean_failures_by_language": {
            k: mean(v) for k, v in sorted(by_lang.items())},
        "per_case": rows,
    }
    print(json.dumps(report, indent=1))
    r = report["pearson_failures_vs_diff_chars"]
    if r is not None and abs(r) >= 0.3:
        print("GUARD (§3.2): failures correlate with diff size "
              f"(r={r}) — widen the reported bounds and say so.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
