#!/usr/bin/env python3
"""Run the test suite FROM the delivery archive (L6 rerun ask,
2026-11-07).

The 571a821 delivery reported a green suite counted in the
working tree; the delivered zip's own suite was red (the
claim-lint pair over bench/stage0-pc/) and the tree count did
not reproduce from the archive. A count is a property of an
artefact, not of a checkout: this script builds the delivery
zip for a ref exactly the way deliveries are built
(`git archive --format=zip`), unpacks it into a fresh
directory, and runs the canonical suite there. Exit status is
the suite's: non-zero means the archive must not ship.

Usage: check_archive_suite.py [git-ref]   (default: HEAD)
"""

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv):
    ref = argv[1] if len(argv) > 1 else "HEAD"
    with tempfile.TemporaryDirectory(
            prefix="codereview-archive-suite-") as tmp:
        archive = Path(tmp) / "delivery.zip"
        built = subprocess.run(
            ["git", "archive", "--format=zip", "-o", str(archive),
             ref],
            cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stderr, file=sys.stderr)
            return 2
        tree = Path(tmp) / "tree"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tree)
        print(f"archive suite: ref={ref} dir={tree}")
        run = subprocess.run(
            [sys.executable, "-m", "unittest", "discover",
             "-s", "tests"],
            cwd=tree, capture_output=True, text=True)
        tail = (run.stderr or run.stdout).strip().splitlines()
        for line in tail[-6:]:
            print(line)
        return run.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
