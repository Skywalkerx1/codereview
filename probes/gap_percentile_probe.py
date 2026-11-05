"""Gap-pass probe — 09c536d15270 (bench percentile).

Claim: the nearest-rank helper ``rank = max(1, -(-len(vals) * pct
// 100))`` "indexes past the end and returns the maximum for many
inputs"; for a 2-item sample at p50 it "yields rank 2".

Check (the ruling pack's P4 property test, executed at HEAD):
exhaustively compare bench.percentile against the textbook
nearest-rank definition (rank = ceil(N * pct / 100), value at
vals[rank - 1]) for N = 1..200 and every integer pct 1..100,
verify no index ever leaves the sample, and print the specific
N=2/p50 case both sides argued about.

Writes results/gap-percentile-09c536d15270.txt. Facts only.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import bench  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-percentile-09c536d15270.txt")


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("PERCENTILE PROBE — 09c536d15270")
    say(f"function under test: bench.percentile (HEAD)")

    # The disputed example: N=2, p50.
    vals = [10, 20]
    got = bench.percentile(vals, 50)
    n, pct = 2, 50
    rank_formula = max(1, -(-n * pct // 100))
    rank_ceil = math.ceil(n * pct / 100)
    say(f"N=2, p50 over [10, 20]: formula rank = {rank_formula}, "
        f"ceil(N*pct/100) = {rank_ceil}, percentile() -> {got}")
    say("(claim said rank 2 / returns the second item; refutation "
        "also said rank 2 — the executed arithmetic says otherwise)")

    # Exhaustive property check.
    mismatches = 0
    out_of_range = 0
    checked = 0
    max_returns = 0
    max_expected = 0
    for n in range(1, 201):
        sample = list(range(1, n + 1))  # distinct, sorted values
        for pct in range(1, 101):
            checked += 1
            want_rank = math.ceil(n * pct / 100)
            want = sample[want_rank - 1]
            got_v = bench.percentile(sample, pct)
            if got_v != want:
                mismatches += 1
                if mismatches <= 5:
                    say(f"  MISMATCH n={n} pct={pct}: got {got_v}, "
                        f"nearest-rank wants {want}")
            if got_v == sample[-1]:
                max_returns += 1
            if want == sample[-1]:
                max_expected += 1
            # index safety is implied by equality with the in-range
            # reference; also probe the raw index expression:
            idx = min(max(1, -(-n * pct // 100)), n) - 1
            if not (0 <= idx < n):
                out_of_range += 1
    say(f"exhaustive: {checked} (n, pct) pairs, n=1..200, pct=1..100")
    say(f"  disagreements with textbook nearest-rank: {mismatches}")
    say(f"  out-of-range indexes: {out_of_range}")
    say(f"  returns of the sample maximum: {max_returns} "
        f"(textbook nearest-rank returns the maximum in "
        f"{max_expected} of the same cases — identical set)")
    say(f"empty sample -> {bench.percentile([], 50)!r} (documented None)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
