#!/usr/bin/env python3
"""Closing-A probe — attempt-2 cc0e75a507fd: function_key allegedly
does an unbounded AST walk with no recursion guard, so deeply
nested source exhausts the stack.

Each shape runs in a SUBPROCESS. Shapes: deeply chained binary
ops / attribute chains / unary ops inside ONE function (these
parse — the PEG parser's own nesting caps stop paren-nesting,
so chains are the shape that reaches the product's walk), plus
attach_function_keys (the caller that invokes function_key with
only its source_lookup guarded).
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
OUT = os.path.join(RESULTS, "closingA-function-key.txt")

lines = []


def emit(msg=""):
    lines.append(msg)
    print(msg)


CHILD = r"""
import sys
sys.path.insert(0, {src!r})
from codereview import core
kind, n = sys.argv[1], int(sys.argv[2])
if kind == "binop": expr = "1" + "+1" * n
elif kind == "attr": expr = "a" + ".b" * n
elif kind == "unary": expr = "-" * n + "1"
src = "def g():\n    return " + expr + "\n"
try:
    k = core.function_key(src, 2)
    print(f"{{kind}} n={{n}}: function_key -> {{'key' if k else None}}")
except BaseException as exc:
    print(f"{{kind}} n={{n}}: function_key RAISED "
          f"{{type(exc).__name__}}: {{str(exc)[:70]}}")
if kind == "binop":
    finding = {{"id": "f1", "file": "g.py", "line": 2}}
    try:
        keyed = core.attach_function_keys([finding], lambda p: src)
        print(f"attach_function_keys -> keyed={{keyed}}")
    except BaseException as exc:
        print(f"attach_function_keys RAISED {{type(exc).__name__}}: "
              f"{{str(exc)[:70]}}")
""".format(src=os.path.join(REPO, "src"))

for kind, n in (("binop", 200), ("binop", 5000), ("attr", 5000),
                ("unary", 5000)):
    try:
        proc = subprocess.run(
            [sys.executable, "-c", CHILD, kind, str(n)],
            capture_output=True, text=True, timeout=30)
        emit(f"[{kind} {n}] exit={proc.returncode} "
             f"{proc.stdout.strip()}")
        if proc.stderr.strip():
            emit(f"  stderr tail: {proc.stderr.strip()[-200:]}")
    except subprocess.TimeoutExpired:
        emit(f"[{kind} {n}] TIMEOUT after 30s")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"\nwrote {OUT}")
