#!/usr/bin/env python3
"""Shadow probe-signature probe — shadow-branch review, for
833912a09fa3 (refutation-weak, authority-affecting):
"Shadow adjudication calls probe_fn with the wrong signature."

The contracts in the tree at HEAD:
- the harness: probe.make_probe_fn(tree) returns
  probe_fn(finding, request) — TWO positional args
  (probe.py), and its docstring calls it "The probe_fn
  contract run_review consumes";
- run_review's own docstring: "probe_fn(finding,
  probe_request) -> {...}";
- the BINDING Tech Lead path calls probe_fn(f,
  decision.get("probe_request") or "") — two args;
- the CLI wires make_probe_fn's fn into run_review by
  default (cli.py), and run_review forwards that same fn to
  shadow_adjudicate;
- shadow_adjudicate calls probe_fn(json.dumps(spec)) — ONE
  arg.

Probe: drive shadow_adjudicate (mirroring
tests/test_shadow_tl.py's seat/payload harness) with a seat
whose first draw says needs_probe with an executable python
spec, and probe_fn = the REAL make_probe_fn over a temp
tree. Record the entry's probe_result. Contrast 1: call the
same harness fn directly with the documented two-arg shape —
the spec executes and its marker prints. Contrast 2: drive
the same shadow path with the suite's own one-arg stub shape
(tests/test_shadow_tl.py's test probe) — it "works", which
is why the suite is green: the only probe test on the
shadow path encodes the one-arg contract the harness does
not implement.

Exit 0 = the signature facts captured in all three runs.

POST-FIX (shadow-fixes branch, after the owner ratified
sustain_finding): the call is probe_fn(finding,
json.dumps(spec)) and a call-boundary TypeError is recorded
as status "wiring_error", can_rebut False. This probe now
verifies the FIXED behaviour in all three runs: run 1's spec
executes through the production wiring; the one-arg stub of
contrast 2 surfaces as a wiring error instead of silently
satisfying the call."""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core, probe  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS,
                   "shadow-probe-signature-833912a09fa3.txt")

REGION = ("import os\n"
          "VALUE = compute_total(items)\n"
          "print(VALUE)\n"
          "RESULT = VALUE * 2\n")
FINDING = {"id": "fx1", "file": "app.py", "line": 2,
           "severity": "major", "title": "Total without guard",
           "evidence": "VALUE = compute_total(items)",
           "evidence_quote": "VALUE = compute_total(items)"}
DISPUTE = {"by": "seatB", "family": "famB",
           "raiser_family": "famA",
           "evidence_quote": "print(VALUE)",
           "reason": "the claim fails on the printed value"}
SPEC = {"kind": "python",
        "code": "print('PROBE_EXECUTED_MARKER')"}

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


def payload(decision="sustain_refutation", **over):
    p = {"claim_restated": "the total lacks a guard",
         "claim_falsifiable": True,
         "position_a_addresses_claim": {"value": True,
                                        "why": "a addresses"},
         "position_b_addresses_claim": {"value": False,
                                        "why": "b misses"},
         "reasoning_assessment": {
             "claim_valid": False,
             "refutation_validity": "valid"},
         "deciding_evidence": {"quote": "print(VALUE)"},
         "probe_request": None,
         "decision": decision,
         "severity_after_rubric": {"level": "major",
                                   "rubric_clause": None},
         "confidence": "high",
         "rationale": "the code shows it"}
    p.update(over)
    return p


class Seat:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def __call__(self, prompt):
        p = self.payloads.pop(0) if len(self.payloads) > 1 \
            else self.payloads[0]
        return p if isinstance(p, str) else json.dumps(p)


def seat_with_probe():
    return Seat([payload(decision="needs_probe",
                         probe_request=SPEC),
                 payload(), payload()])


tree = tempfile.mkdtemp(prefix="codereview-sig-tree-")
try:
    real_fn = probe.make_probe_fn(tree, timeout=30)

    emit("run 1 — shadow_adjudicate with the REAL harness "
         "probe_fn (make_probe_fn, the CLI default wiring):")
    entry = core.shadow_adjudicate(
        seat_with_probe(), dict(FINDING), REGION,
        dict(DISPUTE), seat_name="tl", seat_family="famC",
        probe_fn=real_fn)
    emit(f"  probe_result: {entry['probe_result']}")
    emit(f"  entry state: {entry['state']}; draws: "
         f"{len(entry['draws'])}")
    pr = entry["probe_result"] or {}
    assert pr.get("outcome") == "pass", pr
    assert "PROBE_EXECUTED_MARKER" in (pr.get("output")
                                       or ""), pr
    emit("  -> POST-FIX: shadow_adjudicate calls "
         "probe_fn(finding, json.dumps(spec)); the spec "
         "EXECUTED through the production wiring and its "
         "marker output is in the recorded probe_result "
         "(pre-fix this run recorded a swallowed TypeError "
         "as 'probe failed' and the spec never ran)")

    emit("")
    emit("contrast 1 — the same harness fn called with the "
         "documented probe_fn(finding, request) shape:")
    direct = real_fn(dict(FINDING), json.dumps(SPEC))
    emit(f"  outcome: {direct.get('outcome')}; "
         f"output: {(direct.get('output') or '').strip()!r}")
    assert direct.get("outcome") == "pass", direct
    assert "PROBE_EXECUTED_MARKER" in (direct.get("output")
                                       or "")
    emit("  -> the harness itself is fine; the binding Tech "
         "Lead path (same two-arg call) works")

    emit("")
    emit("contrast 2 — shadow path with the test suite's "
         "one-arg stub (tests/test_shadow_tl.py's "
         "test_probe_round_then_decision):")
    calls = []

    def stub_fn(spec_text):
        calls.append(spec_text)
        return {"status": "supported",
                "detail": "probe output",
                "evidence_quote": "probe output"}

    entry2 = core.shadow_adjudicate(
        seat_with_probe(), dict(FINDING), REGION,
        dict(DISPUTE), seat_name="tl", seat_family="famC",
        probe_fn=stub_fn)
    emit(f"  stub calls: {len(calls)}; probe_result: "
         f"{entry2['probe_result']}")
    pr2 = entry2["probe_result"] or {}
    assert pr2.get("status") == "wiring_error", pr2
    assert pr2.get("can_rebut") is False, pr2
    emit("  -> POST-FIX: the one-arg stub no longer "
         "satisfies the call — its TypeError is recorded "
         "as a distinct wiring_error (can_rebut False), "
         "never as probe evidence; the suite stub now "
         "implements the real two-arg contract (pre-fix "
         "this stub 'worked', which is why the suite "
         "stayed green over a dead channel)")
finally:
    shutil.rmtree(tree, ignore_errors=True)

emit("")
emit("VERDICT FACTS (post-fix): the shadow probe round "
     "executes through the production wiring — run 1's "
     "spec ran and its marker is in the recorded "
     "probe_result; a miswired callable surfaces as "
     "status 'wiring_error' with can_rebut False instead "
     "of masquerading as a probe result. Pre-fix, every "
     "shadow needs_probe round fed draw 2 a swallowed "
     "TypeError as 'probe failed' evidence and the spec "
     "never ran (833912a09fa3, sustained; fixed in the "
     "shadow-fixes branch).")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
