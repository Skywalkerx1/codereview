"""Gap-pass probe — eae8137a6db3 + 3cecf66f6ce5 (commonpath).

Claims: _load_fixture_scope (eae8137a6db3) and _load_precedents
(3cecf66f6ce5) called os.path.commonpath unguarded, so a path on
a different Windows drive (or otherwise incomparable) raises a
raw ValueError instead of the intended validation error.

Check at HEAD: both loaders route containment through the
shared cli._is_within helper, which catches ValueError and
fails closed. Executed: (1) _is_within under a monkeypatched
commonpath that raises ValueError (the cross-drive failure
mode, simulated — real Windows drives cannot exist on this
Linux host; the POSIX mixed absolute/relative case raises the
same exception from the same call and is shown directly);
(2) both loaders against an outside-repo path produce the
intended validation error; (3) git evidence that the unguarded
calls existed at the fixing commit's parent and were replaced
by 4e5cbd8 (v0.9.6).

Writes results/gap-commonpath-pair.txt. Facts only.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results",
                   "gap-commonpath-pair.txt")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    lines = []

    def say(s=""):
        lines.append(s)
        print(s)

    say("COMMONPATH PAIR PROBE — eae8137a6db3 + 3cecf66f6ce5")
    say("")
    say("== the raw failure mode (POSIX form, same exception) ==")
    try:
        os.path.commonpath(["/abs/path", "relative/path"])
        say("  commonpath(['/abs/path', 'relative/path']) did "
            "not raise (unexpected)")
    except ValueError as exc:
        say(f"  commonpath(['/abs/path', 'relative/path']) -> "
            f"ValueError: {exc}")

    say("")
    say("== _is_within at HEAD, incl. simulated cross-drive ==")
    say(f"  normal inside:  _is_within('/a/b/c', '/a/b') = "
        f"{cli._is_within('/a/b/c', '/a/b')}")
    say(f"  normal outside: _is_within('/a/x', '/a/b') = "
        f"{cli._is_within('/a/x', '/a/b')}")
    say(f"  mixed abs/rel:  _is_within('/a/b', 'rel/root') = "
        f"{cli._is_within('/a/b', 'rel/root')} (no exception)")
    real_commonpath = os.path.commonpath

    def cross_drive(_paths):
        raise ValueError("Paths don't have the same drive")

    os.path.commonpath = cross_drive
    try:
        got = cli._is_within("/a/b/c", "/a/b")
    finally:
        os.path.commonpath = real_commonpath
    say(f"  commonpath raising ValueError (simulated Windows "
        f"cross-drive): _is_within -> {got} (fails closed, "
        f"no propagation)")

    say("")
    say("== both loaders at HEAD, outside-repo path ==")
    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "repo")
        os.makedirs(repo)
        outside = os.path.join(td, "outside.json")
        with open(outside, "w") as fh:
            fh.write("{}")
        for name, fn in (("_load_fixture_scope",
                          cli._load_fixture_scope),
                         ("_load_precedents", cli._load_precedents)):
            try:
                fn(outside, repo=repo)
                say(f"  {name}(outside) -> returned (unexpected)")
            except ValueError as exc:
                say(f"  {name}(outside) -> ValueError (intended "
                    f"validation error): {str(exc)[:100]}")
            except Exception as exc:  # noqa: BLE001
                say(f"  {name}(outside) -> {type(exc).__name__}: "
                    f"{exc}")

    say("")
    say("== git: the unguarded pattern and its fix ==")
    for rev in ("4e5cbd8^", "4e5cbd8"):
        blob = subprocess.run(
            ["git", "show", f"{rev}:src/codereview/cli.py"],
            cwd=REPO, capture_output=True, text=True).stdout
        direct = blob.count(
            "os.path.commonpath([full, repo_abs]) != repo_abs")
        helper = blob.count("def _is_within")
        say(f"  {rev}: direct commonpath containment checks in "
            f"loaders: {direct}; _is_within helper defined: "
            f"{helper}")
    say("  fixing commit 4e5cbd8 (v0.9.6) docstring in _is_within "
        "cites both finding IDs: 'the mechanism was real, the "
        "severity was not — one shared helper, used at both "
        "loader call sites'.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
