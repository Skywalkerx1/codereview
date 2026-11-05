"""Gap-pass probe — 474297e6ffdc (bench --force degraded check).

Claim: during --force, new records are appended onto previously
loaded ones, so the post-run degraded check evaluates OLD
records too and a healthy forced rerun is refused because a
prior degraded record exists.

Check (the ruling pack's P3, executed at HEAD): seed a stored
results file whose only record is degraded (valid resume
hashes), force-rerun with healthy seats — the swap must succeed;
then force-rerun with a failing seat — the swap must be refused
AND the previous file must survive intact.

Writes results/gap-bench-force-474297e6ffdc.txt. Facts only.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-bench-force-474297e6ffdc.txt")

CLEAN_DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,2 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""


def _pass(_prompt):
    return json.dumps({"verdict": "pass", "summary": "looks fine",
                       "findings": []})


def _boom(_prompt):
    raise RuntimeError("provider down")


def _write_case(root, cid):
    cdir = os.path.join(root, cid)
    os.makedirs(cdir)
    meta = {"id": cid, "title": f"case {cid}",
            "category": "clean", "split": "public",
            "source": "gap probe fixture", "license": "MIT",
            "expected": []}
    with open(os.path.join(cdir, "case.json"), "w") as fh:
        json.dump(meta, fh)
    with open(os.path.join(cdir, "diff.patch"), "w") as fh:
        fh.write(CLEAN_DIFF)


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("BENCH FORCE PROBE — 474297e6ffdc")
    say("function under test: bench.run_bench(force=True) at HEAD")
    with tempfile.TemporaryDirectory() as td:
        corpus = os.path.join(td, "corpus")
        os.makedirs(os.path.join(td, "configs"))
        os.makedirs(os.path.join(td, "scripts"))
        _write_case(corpus, "clean-one")
        with open(os.path.join(td, "scripts", "oracle.json"),
                  "w") as fh:
            json.dump({"default": {"verdict": "pass",
                                   "summary": "nothing",
                                   "findings": []}}, fh)
        with open(os.path.join(td, "configs", "oracle.json"),
                  "w") as fh:
            json.dump({"name": "oracle",
                       "providers": [{
                           "name": "oracle",
                           "script": "../scripts/oracle.json"}]},
                      fh)
        out = os.path.join(td, "out")
        healthy = {"oracle": {"ok": _pass}}

        # 1. A normal run stores one healthy record.
        bench.run_bench(corpus, ["oracle"], out,
                        providers_by_config=healthy)
        path = os.path.join(out, "oracle.jsonl")
        with open(path) as fh:
            stored = [json.loads(x) for x in fh if x.strip()]
        say(f"  stored after healthy run: {len(stored)} record(s), "
            f"degraded={stored[0]['degraded']}")

        # 2. Age the stored record into a degraded one (same
        #    resume hashes — a faithful 'bad day' artifact).
        stored[0]["degraded"] = True
        with open(path, "w") as fh:
            fh.write(json.dumps(stored[0]) + "\n")
        say("  stored file rewritten: sole record now "
            "degraded=true (patch/config hashes untouched)")

        # 3. THE CLAIM'S SCENARIO: forced rerun, all seats
        #    healthy, old degraded record on disk.
        try:
            results = bench.run_bench(
                corpus, ["oracle"], out, force=True,
                providers_by_config=healthy)
            with open(path) as fh:
                after = [json.loads(x) for x in fh if x.strip()]
            say(f"  forced healthy rerun: ACCEPTED — results "
                f"returned {len(results['oracle'])} record(s); "
                f"file now holds {len(after)} record(s), "
                f"degraded={after[0]['degraded']}")
        except ValueError as exc:
            say(f"  forced healthy rerun: REFUSED — {exc}")

        # 4. Control (P3 second half): forced rerun whose NEW
        #    records are degraded must be refused, and the file
        #    from step 3 must survive intact.
        with open(path) as fh:
            before = fh.read()
        try:
            bench.run_bench(corpus, ["oracle"], out, force=True,
                            providers_by_config={
                                "oracle": {"bad": _boom}})
            say("  forced degraded rerun: ACCEPTED (unexpected)")
        except ValueError as exc:
            say(f"  forced degraded rerun: REFUSED — "
                f"{str(exc)[:110]}")
        with open(path) as fh:
            say(f"  previous file intact after refusal: "
                f"{fh.read() == before}")
    say("mechanism at HEAD: under force, stored records are never "
        "loaded (run_bench skips the resume block when force is "
        "set; 'records' starts empty), so the degraded check "
        "sees only this run's records. The same held at the v15 "
        "record's own head (e3fc6a8: bench.py lines 484-491).")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
