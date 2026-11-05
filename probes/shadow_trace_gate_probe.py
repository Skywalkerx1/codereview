#!/usr/bin/env python3
"""Trace-gate forward-reference probe — shadow-branch review,
for 4cba208656d3 (disputed): "_trace_gate_shadow references
_scan_functions before its definition."

Claim mechanism: `_trace_gate_shadow` (defined earlier in
core.py) calls `_scan_functions` (defined later), which the
raiser presents as a defect. The refutation answers with
Python semantics: a name referenced inside a function body is
resolved at CALL time, not definition time — the claim needs
a call path that executes before the module finishes loading,
and there is none (the reference sits inside a function body,
not at module scope).

Probe: (1) record the definition order at HEAD from the
module source; (2) import the module (import itself executes
every def — no error); (3) CALL `_trace_gate_shadow` on a
major finding whose cited line calls a callee defined in the
region, with the callee's body quoted in the evidence — the
evaluation must come back applies=True with the callee named,
which is only possible if the `_scan_functions(region_text)`
line inside `_trace_gate_shadow` executed and returned the
region's definitions; (4) contrast: same call with the body
NOT quoted — would_downgrade must flip to True, proving the
scan results drive the verdict both ways.

Exit 0 = the forward reference resolved at call time and the
trace gate executed end to end."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "shadow-trace-gate-4cba208656d3.txt")

REGION = ("def compute_total(items):\n"
          "    return sum(items)\n"
          "\n"
          "VALUE = compute_total(items)\n")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


src_lines = open(core.__file__, encoding="utf-8").read().splitlines()
def_line = {name: next(i + 1 for i, ln in enumerate(src_lines)
                       if ln.startswith(f"def {name}"))
            for name in ("_trace_gate_shadow", "_scan_functions")}
emit(f"definition order at HEAD ({core.__file__}):")
emit(f"  def _trace_gate_shadow at line {def_line['_trace_gate_shadow']}")
emit(f"  def _scan_functions    at line {def_line['_scan_functions']}")
ref_line = next(i + 1 for i, ln in enumerate(src_lines)
                if "defs = _scan_functions(region_text)" in ln)
emit(f"  -> the reference inside _trace_gate_shadow's body "
     f"(line {ref_line}, "
     f"`defs = _scan_functions(region_text) or []`) precedes "
     f"the definition textually: "
     f"{def_line['_trace_gate_shadow'] < def_line['_scan_functions']}")
emit("module import: OK (every def executed at import; the "
     "referenced name is not touched at definition time)")

base = {"id": "probe-tg", "severity": "major",
        "file": "app.py", "line": 4,
        "title": "claim about the callee compute_total"}

quoted = dict(base, evidence="the body shows it directly:\n"
                             "    return sum(items)",
              evidence_quote="    return sum(items)")
res1 = core._trace_gate_shadow(quoted, REGION)
emit("")
emit(f"call 1 (callee body quoted in evidence): {res1}")
assert res1["applies"] is True, res1
assert res1["about_callee"] == ["compute_total"], res1
assert res1["callee_body_quoted"] is True, res1
assert res1["would_downgrade"] is False, res1
emit("  -> _scan_functions executed at call time and returned "
     "the region's defs; no NameError")

unquoted = dict(base, evidence="no body line is quoted",
                evidence_quote="VALUE = compute_total(items)")
res2 = core._trace_gate_shadow(unquoted, REGION)
emit("")
emit(f"call 2 (callee body NOT quoted): {res2}")
assert res2["applies"] is True, res2
assert res2["callee_body_quoted"] is False, res2
assert res2["would_downgrade"] is True, res2
emit("  -> the scan results drive the verdict both ways; the "
     "forward-referenced call is on the executed path")

emit("")
emit("VERDICT FACTS: definition order is as the claim says; "
     "the mechanism (a defect from referencing a later-defined "
     "function inside a function body) does not reproduce — "
     "the call resolves at call time and the gate evaluates "
     "correctly in both directions.")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
