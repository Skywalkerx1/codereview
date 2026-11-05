"""Gap-pass probe — d93089253022 (directory pattern overmatch).

Claim: core.path_matches treats a plain pattern 'foo' as a
directory prefix, so 'foobar/...' also matches and unrelated
files get classified as fixtures.

Check (the ruling pack's P9 pattern-normalization matrix,
executed at HEAD): run the matcher over sibling-prefix,
exact, child, glob, and dir/** cases and print every result.

Writes results/gap-matcher-d93089253022.txt. Facts only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-matcher-d93089253022.txt")

CASES = [
    # (path, patterns, claim-relevant expectation)
    ("foobar/x.py", ["foo"], "sibling prefix — claim says MATCHES"),
    ("foobar", ["foo"], "sibling exact-name — claim implies match"),
    ("foo/x.py", ["foo"], "true child of the directory"),
    ("foo", ["foo"], "the directory itself"),
    ("foo/", ["foo"], "trailing-slash path form"),
    ("foo/x.py", ["foo/"], "pattern with trailing slash"),
    ("foobar/x.py", ["foo/"], "sibling vs slashed pattern"),
    ("foobar/x.py", ["foo/**"], "sibling vs dir/** form"),
    ("foo/x.py", ["foo/**"], "child vs dir/** form"),
    ("foo", ["foo/**"], "base of dir/** form"),
    ("a/foo/x.py", ["foo"], "non-rooted sibling segment"),
    ("tests/fixtures/x.py", ["tests/fixtures"], "realistic fixture dir"),
    ("tests/fixtures2/x.py", ["tests/fixtures"], "realistic sibling"),
    ("foo/bar.py", ["f*"], "glob form still works"),
    ("foo/bar.py", ["foo/*.py"], "glob with directory"),
]


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("PATH MATCHER PROBE — d93089253022")
    say("function under test: core.path_matches (HEAD)")
    for path, pats, note in CASES:
        got = core.path_matches(path, pats)
        say(f"  path_matches({path!r}, {pats!r}) = {got}   # {note}")
    sib = core.path_matches("foobar/x.py", ["foo"])
    say(f"headline case: sibling 'foobar/x.py' vs pattern 'foo' "
        f"-> {sib} (claim: matched/overmatch; matcher requires "
        f"path == base or path.startswith(base + '/'))")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
