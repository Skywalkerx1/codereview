#!/usr/bin/env python3
"""Build bench/generation-v3/manifest.json from the case directories.

The corpus manifest follows bench/expanded-clean/manifest.json's
shape (schema codereview.benchcorpus/1): src/codereview/bench.py's
load_corpus requires its case-id list to agree exactly with the
case directories on disk. Entries carry one extra field, `stratum`,
which the loader ignores and the seal/scoring use to keep the
sub-labels distinct. Stdlib only.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SET_DIR = os.path.dirname(HERE)


def main():
    ids = sorted(
        d for d in os.listdir(SET_DIR)
        if os.path.isfile(os.path.join(SET_DIR, d, "case.json")))
    cases = []
    for cid in ids:
        with open(os.path.join(SET_DIR, cid, "case.json"),
                  encoding="utf-8") as fh:
            meta = json.load(fh)
        if meta.get("id") != cid:
            raise SystemExit(f"{cid}: case.json id mismatch")
        stratum = meta.get("stratum")
        if not stratum:
            raise SystemExit(f"{cid}: missing stratum")
        cases.append({
            "id": cid,
            "category": meta["category"],
            "split": meta["split"],
            "expected_defects": len(meta.get("expected") or []),
            "stratum": stratum,
        })
    manifest = {
        "schema": "codereview.benchcorpus/1",
        "stratum": "generation-v3",
        "version": "0",
        "cases": cases,
    }
    out = os.path.join(SET_DIR, "manifest.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"wrote {out}: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
