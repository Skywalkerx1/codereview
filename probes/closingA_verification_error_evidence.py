#!/usr/bin/env python3
"""Closing-A probe — attempt-2 30b316c77b43 / attempt-1 328a5ff6fa51
(verification `raise res["error"]` on a non-Exception error payload)
and attempt-2 2eb60efeeace / attempt-1 f9ca50d61cad (verification
resolution evidence length cap).

Part A: force a failed-job dict whose "error" is a plain STRING
(the _review_job_bounded timeout/invalid-timeout shape) into
run_verification by replacing core._review_job (the producer
interface run_verification consumes), and watch whether the
TypeError from `raise <str>` escapes run_verification.
Control A2: the real producer path — a provider raising
RuntimeError — and the type _review_job actually stores.

Part B: a provider returns a resolution carrying 5000 chars of
evidence; measure the length stored in the returned report, then
write_report and measure the JSON display copy + sidecar file.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-verification-error-evidence.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


PATCH = "diff --git a/a.py b/a.py\n+alpha beta gamma delta\n"
PRIOR = {"gate": "blocked", "findings": [
    {"id": "prior1", "severity": "major", "title": "t",
     "file": "a.py", "sources": ["seatA"]}]}

# --- Part A1: forced string error payload -------------------------
orig_job = core._review_job


def fake_job_str_error(fn, prompt, sleep=None, max_attempts=None):
    # The exact failed-job shape _review_job_bounded returns on a
    # timeout / invalid timeout: "error" is a plain string.
    return {"ok": False, "parsed": None,
            "error": "Tech Lead call timed out after 5s",
            "attempts": 0, "error_classes": ["timeout"]}


core._review_job = fake_job_str_error
try:
    try:
        rep = core.run_verification(
            PATCH, {"seatA": lambda prompt: "{}"}, PRIOR, "",
            sleep=lambda *a: None)
        emit("A1 run_verification RETURNED (no exception escaped)")
        rec = rep["reviewer_reports"][0]
        emit(f"A1 rec status={rec['status']!r} error={rec['error']!r}")
        emit(f"A1 gate={rep['gate']!r} degraded={rep.get('degraded')!r}")
    except BaseException as exc:  # noqa: BLE001
        emit(f"A1 run_verification RAISED {type(exc).__name__}: {exc}")
finally:
    core._review_job = orig_job

# --- Part A2: real producers --------------------------------------
res = core._review_job(
    lambda prompt: (_ for _ in ()).throw(RuntimeError("seat blew up")),
    "p", sleep=lambda *a: None)
emit(f"A2 _review_job error type: {type(res['error']).__name__} "
     f"is_exception={isinstance(res['error'], BaseException)}")
res_b = core._review_job_bounded(lambda prompt: "{}", "p", timeout=0)
emit(f"A2 _review_job_bounded(timeout=0) error type: "
     f"{type(res_b['error']).__name__} value={res_b['error']!r}")
try:
    rep2 = core.run_verification(
        PATCH,
        {"seatA": lambda prompt: (_ for _ in ()).throw(
            RuntimeError("seat blew up"))},
        PRIOR, "", sleep=lambda *a: None)
    rec2 = rep2["reviewer_reports"][0]
    emit(f"A2 real raising provider: RETURNED, rec error={rec2['error']!r}")
except BaseException as exc:  # noqa: BLE001
    emit(f"A2 real raising provider RAISED {type(exc).__name__}: {exc}")

# --- Part B: resolution evidence length ---------------------------
EVID = ("alpha beta gamma delta " * 220)[:5000]
assert len(EVID) == 5000


def seat(prompt):
    return json.dumps({"resolutions": [
        {"finding_id": "prior1", "status": "still_present",
         "evidence": EVID}], "new_findings": []})


rep3 = core.run_verification(PATCH, {"seatA": seat}, PRIOR, "",
                             sleep=lambda *a: None)
entry = rep3["reviewer_reports"][0]["resolutions"]["prior1"]
emit(f"B in-memory stored evidence length: {len(entry['evidence'])}")
with tempfile.TemporaryDirectory() as td:
    jpath, _mpath = core.write_report(rep3, td, stem="probe")
    written = json.load(open(jpath, encoding="utf-8"))
    wentry = written["reviewer_reports"][0]["resolutions"]["prior1"]
    ref = wentry["evidence_ref"]
    sidecar = os.path.join(td, "evidence", ref["sha256"])
    with open(sidecar, encoding="utf-8") as fh:
        full = fh.read()
    emit(f"B written JSON display length: {len(wentry['evidence'])} "
         f"ref={ref}")
    emit(f"B sidecar full-text length: {len(full)}")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
