#!/usr/bin/env python3
"""Validation harness for the generation-v3 sealed set (build-time only).

For every case it extracts the post-image files from the case's
diff.patch into a temp tree and runs the case's behavioural check
(validation/<case-id>/check.py, a plain assert script) against them:

  * clean-authored / clean-realworld (with a check): check must PASS
    (exit 0) on the case code.
  * defect-injected: check must FAIL (non-zero exit) on the case code
    (the defect is demonstrated), and must PASS after the files in
    validation/<case-id>/fixed/ are overlaid (the pre/post pair
    defines the label).
  * defect-realworld: check must FAIL on the case code when a check
    exists (defect demonstrated); a fixed/ overlay is optional.

Usage: run_validation.py [--json OUT] [case-id ...]
With no ids, validates every case directory under bench/generation-v3.
Exit 0 iff every selected case validates as expected.
Stdlib only.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SET_DIR = os.path.dirname(HERE)


def extract_post_image(diff_path, dest):
    """Write the added-file contents of a new-file-only unified diff."""
    files = {}
    current = None
    with open(diff_path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("diff --git "):
                current = None
            elif line.startswith("+++ b/"):
                current = line[len("+++ b/"):]
                files.setdefault(current, [])
            elif line.startswith("+++"):
                current = None
            elif current is not None and line.startswith("+"):
                files[current].append(line[1:])
            elif line.startswith("@@"):
                pass
    if not files:
        raise ValueError(f"{diff_path}: no added files parsed")
    written = []
    for rel, lines in files.items():
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written.append(rel)
    return written


def run_check(workdir):
    proc = subprocess.run(
        [sys.executable, "check.py"],
        cwd=workdir,
        env={**os.environ, "PYTHONPATH": workdir,
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=120)
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, (tail[-1] if tail else "")


def validate_case(case_id):
    case_dir = os.path.join(SET_DIR, case_id)
    val_dir = os.path.join(HERE, case_id)
    with open(os.path.join(case_dir, "case.json"),
              encoding="utf-8") as fh:
        meta = json.load(fh)
    stratum = meta.get("stratum") or ""
    check_src = os.path.join(val_dir, "check.py")
    has_check = os.path.isfile(check_src)
    result = {"case_id": case_id, "stratum": stratum,
              "has_check": has_check}
    if not has_check:
        if stratum == "clean-realworld":
            result.update(ok=True, mode="standing-verified-only")
            return result
        if stratum == "defect-realworld" and os.path.isfile(
                os.path.join(val_dir, "TRIGGER.md")):
            result.update(ok=True, mode="trigger-documented")
            return result
        result.update(ok=False, mode="missing-check",
                      detail="validation check.py is required")
        return result
    tmp = tempfile.mkdtemp(prefix=f"v3val-{case_id}-")
    try:
        extract_post_image(os.path.join(case_dir, "diff.patch"), tmp)
        shutil.copy(check_src, os.path.join(tmp, "check.py"))
        rc, tail = run_check(tmp)
        result["defect_code_check_rc"] = rc
        result["defect_code_check_tail"] = tail[:300]
        if stratum.startswith("clean"):
            result.update(ok=(rc == 0), mode="check-must-pass")
            return result
        # defect strata: the check asserts CORRECT behaviour, so it
        # must fail on the case (defect) code.
        if rc == 0:
            result.update(ok=False, mode="check-must-fail",
                          detail="check passed on defect code — "
                                 "defect not demonstrated")
            return result
        fixed_dir = os.path.join(val_dir, "fixed")
        if os.path.isdir(fixed_dir):
            for root, _dirs, names in os.walk(fixed_dir):
                for name in names:
                    src = os.path.join(root, name)
                    rel = os.path.relpath(src, fixed_dir)
                    dst = os.path.join(tmp, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(src, dst)
            rc2, tail2 = run_check(tmp)
            result["fixed_code_check_rc"] = rc2
            result["fixed_code_check_tail"] = tail2[:300]
            result.update(ok=(rc2 == 0), mode="fail-then-fix-passes")
            return result
        if stratum == "defect-injected":
            result.update(ok=False, mode="missing-fixed-overlay",
                          detail="injected defects require fixed/")
            return result
        result.update(ok=True, mode="check-fails-on-defect")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    rest = list(argv[1:])
    json_out = None
    if "--json" in rest:
        i = rest.index("--json")
        json_out = rest[i + 1]
        del rest[i:i + 2]
    args = [a for a in rest if not a.startswith("--")]
    if args:
        ids = args
    else:
        ids = sorted(
            d for d in os.listdir(SET_DIR)
            if os.path.isfile(os.path.join(SET_DIR, d, "case.json")))
    results = [validate_case(cid) for cid in ids]
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"{mark} {r['case_id']:<34} {r['stratum']:<18} "
              f"{r['mode']}" +
              (f" — {r['detail']}" if not r["ok"] and
               r.get("detail") else ""))
    bad = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(bad)}/{len(results)} cases validate")
    if json_out:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump({"results": results,
                       "ok": len(results) - len(bad),
                       "total": len(results)}, fh, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
