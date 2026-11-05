#!/usr/bin/env python3
"""Duplicate-seat demonstration — open-refutations solution
§3, for 78ddf4d5ea27 (bucket D #10), taken jointly with
19a537eb386b's seat question (§3: 'duplicate-seat question in
#10' shares this seam).

Claim: with the same preset spec listed twice (a pooled seat)
plus a --role override naming the same preset with a
different model, the override is a no-op for what serves, yet
role_models records the override model — the record says a
model served that never did.

This is a DEMONSTRATION, not a guard assertion: it reproduces
the recorded-vs-served mismatch with a stubbed transport and
prints both sides. It also checks the name-level half that
CAN be asserted: seat names/account counts are identical
across spec orderings (permutation determinism).

Exit 0 = the demonstration ran and the facts printed are
internally consistent (whichever way they land)."""

import itertools
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import cli, providers  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

OC = {"choices": [{"message": {"content": "ok"}}]}
ENV = {"OPENAI_API_KEY": "k-one", "OPENAI_API_KEY_2": "k-two",
       "GEMINI_API_KEY": "k-gem"}


def served_models(seat_fn):
    """Invoke every account behind a seat with a stubbed
    transport; return the payload models actually sent."""
    calls = []

    def fake(url, headers, payload, timeout=240):
        calls.append(payload)
        return OC
    with mock.patch.object(providers, "_post_json", fake):
        accounts = getattr(seat_fn, "accounts", None)
        if accounts:
            for _label, fn in accounts:
                fn("probe")
        else:
            seat_fn("probe")
    return [c["model"] for c in calls]


def main():
    lines = ["DUPLICATE-SEAT DEMONSTRATION — 78ddf4d5ea27",
             "(jointly with 19a537eb386b's seat seam)", ""]
    with mock.patch.dict(os.environ, ENV):
        panel = providers.build_providers(["openai", "openai"])
        seat = panel["openai"]
        labels = [lbl for lbl, _fn in seat.accounts]
        default_model = providers.describe_spec("openai")["model"]
        before = served_models(seat)
        lines += [
            "Panel built from ['openai', 'openai'] (two keys in",
            "env): one seat 'openai', an account pool:",
            f"  account labels (key-env names): {labels}",
            f"  registry default model: {default_model!r}",
            f"  models the pool actually sends: {before}",
            "",
            "Now apply --role correctness=openai:gpt-9.9-probe",
            "(an override model) against that pooled seat:",
        ]
        _lens, seat_roles, role_models, _tl = \
            cli._apply_role_assignments(
                panel, ["correctness=openai:gpt-9.9-probe"])
        recorded = role_models["correctness"]["model"]
        after = served_models(panel["openai"])
        same_object = panel["openai"] is seat
        lines += [
            f"  seat_roles: {seat_roles}",
            f"  role_models['correctness']['model'] recorded: "
            f"{recorded!r}",
            f"  panel seat object unchanged: {same_object}",
            f"  models the seat actually sends afterwards: {after}",
            "",
        ]
        mismatch = recorded not in after
        lines.append(
            "DEMONSTRATED: the record credits model "
            f"{recorded!r} with the correctness role, but the "
            "seat that serves sends "
            f"{sorted(set(after))} — the override callable was "
            "built, discarded on the name collision, and its "
            "model recorded anyway. The claim's mechanism "
            "reproduces exactly at HEAD."
            if mismatch else
            "NOT REPRODUCED: the recorded model is among the "
            "models the seat sends — the claim's mechanism does "
            "not reproduce at HEAD.")

        # Permutation determinism (name level — assertable).
        lines += ["",
                  "Permutation check (seat names + pool sizes "
                  "across orderings):"]
        shapes = {}
        for ordering in itertools.permutations(
                ["openai", "openai", "gemini"]):
            p = providers.build_providers(list(ordering))
            shape = {n: len(getattr(fn, "accounts", [fn]))
                     for n, fn in p.items()}
            shapes[ordering] = shape
        distinct = {tuple(sorted(s.items()))
                    for s in shapes.values()}
        for ordering, shape in shapes.items():
            lines.append(f"  {ordering} -> {shape}")
        lines.append(f"  distinct shapes across orderings: "
                     f"{len(distinct)}")
        assert len(distinct) == 1, "seat naming is order-dependent"
        lines.append("  HELD: seat names and pool sizes are "
                     "permutation-invariant; only the recorded "
                     "role model diverges from what serves.")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "duplicate-seat-78ddf4d5ea27.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
