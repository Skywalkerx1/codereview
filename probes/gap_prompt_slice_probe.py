"""Gap-pass probe — 3f50bf6b3349 (_prompt_slice cap).

Claim: the prompt truncation helper can return strings longer
than the requested cap. Refutation (adequacy: weak) argues the
output length is set by the slice plus a fixed marker, not by
the original text — which concedes the sum can exceed the cap.

Check: measure len(_prompt_slice(text, cap)) against cap over
boundary cases at HEAD and quantify the overshoot.

Writes results/gap-prompt-slice-3f50bf6b3349.txt. Facts only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-prompt-slice-3f50bf6b3349.txt")

CASES = [
    ("under cap", "hello world", 300),
    ("exactly cap", "x" * 100, 100),
    ("one over cap", "x" * 101, 100),
    ("long prose", ("the quick brown fox jumps over the lazy dog "
                    * 40).strip(), 300),
    ("long single word", "x" * 5000, 300),
    ("small cap, long text", "word " * 500, 50),
    ("cap 1", "hello", 1),
]


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("PROMPT SLICE PROBE — 3f50bf6b3349")
    say("function under test: core._prompt_slice (HEAD)")
    worst = 0
    for name, text, cap in CASES:
        out = core._prompt_slice(text, cap)
        over = len(out) - cap
        worst = max(worst, over)
        say(f"  {name}: len(text)={len(text)} cap={cap} -> "
            f"len(out)={len(out)} (over cap by {over})")
        if len(text) > cap:
            say(f"    out tail: ...{out[-60:]!r}")
    say(f"maximum overshoot across cases: {worst} chars — bounded "
        f"by the fixed truncation marker (full-length + sha256), "
        f"which the helper appends AFTER slicing to the cap; the "
        f"docstring promises 'at most cap chars'.")
    say("callers: _finding_public / prompt construction slice "
        "evidence for adjudication prompts; the stored record "
        "text is never cut by this helper.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
