#!/usr/bin/env python3
"""Closing-A probe — attempt-2 dd391599588d: in run_verification,
new findings are normalized with `serving_name` instead of the
primary seat's `name` (line: nf = _normalize_finding(raw_f,
serving_name)) — allegedly wrong attribution.

Scenario where the two differ: the primary seat fails and a
fallback seat serves the job and raises a NEW finding. Observe
(a) the finding's sources, (b) the reviewer report's provider,
(c) consistency with the finder rule (the serving seat is the
seat recorded as having raised it).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-serving-name.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


PATCH = "diff --git a/a.py b/a.py\n+alpha beta gamma delta\n"
PRIOR = {"gate": "blocked", "findings": [
    {"id": "prior1", "severity": "major", "title": "t",
     "file": "a.py", "sources": ["primary"]}]}


def primary(prompt):
    raise RuntimeError("primary seat down")


def fallback(prompt):
    return json.dumps({
        "resolutions": [{"finding_id": "prior1", "status": "fixed",
                         "evidence": "alpha beta gamma delta fixed"}],
        "new_findings": [{
            "severity": "major", "title": "New defect from fallback",
            "file": "a.py", "line": 1, "category": "correctness",
            "evidence": "alpha beta", "confidence": 0.9}]})


emit(f"LENSES order: {core.LENSES}")
lens0 = list(core.LENSES)[0]
rep = core.run_verification(
    PATCH, {"primary": primary}, PRIOR, "",
    fallbacks={lens0: ("fbseat", fallback)}, sleep=lambda *a: None)
rec = rep["reviewer_reports"][0]
emit(f"reviewer report: provider={rec['provider']!r} "
     f"fallback_for={rec.get('fallback_for')!r} status={rec['status']!r}")
for f in rep["findings"]:
    emit(f"new finding {f['id']}: sources={f['sources']!r} "
         f"title={f['title']!r}")
emit(f"cleared: {[f['id'] for f in rep['cleared']]} "
     f"gate={rep['gate']!r}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
