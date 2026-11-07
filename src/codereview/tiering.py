#!/usr/bin/env python3
"""Tiered panels and escalation — Epic E2 + E4 of the adopted
roadmap.

E1's risk scorer describes a change; this module ACTS on the
description to size the panel that reviews it:

  * band "low"    → a designated pre-screen seat (or seats)
                    only;
  * band "medium" → a reduced panel;
  * band "high"   → the full panel, and evidence is required
                    (the Epic C rule: required evidence that
                    is missing BLOCKS the gate). "Missing"
                    includes the run where the caller supplied
                    no evidence record at all — the tiering
                    policy is itself the requirement. A supplied
                    record whose required item is UNAVAILABLE
                    (tool not installed) is the other C3 branch
                    and makes the gate INCONCLUSIVE instead
                    (P6-11: the two statuses are per-item, and
                    an absent record is not an item).

E4 is the safety valve on the smaller tiers: if the
pre-screen / reduced panel returns uncertainty or any
blocking finding, the run escalates to the full panel WITHIN
the same run. The triggers are stated in the product's
existing vocabulary, never a parallel one:

  * "blocking finding" — a stage-1 reviewer report carries a
    finding whose severity is in the gate's blocking set
    (the same set core._gate applies, allow_major included);
  * "reviewer failure" — a stage-1 reviewer job ended in
    error after its fallbacks: the seat could not answer, so
    the small panel's answer is incomplete by the run's own
    degraded vocabulary;
  * "lens unserved: <lens>" — a lens the full panel tasks has
    no successful stage-1 report while stage-2 seats remain
    to serve it: the small panel structurally did not cover
    the change (the S1/coverage vocabulary).

Escalation never removes anything: stage-1 reports and
findings stay in the run, and the final verdict is computed
on the full evidence of the run by the normal gate rules.
A finding the pre-screen raised is neither withdrawn nor
discounted because the full panel also served.

Configuration lives in the [risk] table of .codereview.toml
(policy.py validates it in the B1 style): `tiering = true`
turns the machinery on (it consumes the band, so [risk]
`enabled` must be true too — policy load rejects the
combination otherwise). `prescreen_seats` names the low
tier's seats (default: the first seat of the composed
panel); `medium_seats` names the medium tier's seats
(default: the first tasked seat per lens). A configured name
that is not on the composed panel is recorded in the run's
`tiering` section as a missing seat — never silently
dropped — and if filtering would leave a tier with NO seats
at all, the run falls back to the full panel with the
reason recorded: a configuration accident must never produce
an unreviewed run.

Seat–lens binding (S1) is untouched: under an explicit
binding, tiering filters the derived task list by seat, so
a seat serves exactly its bound lens(es) at every tier — a
reduced panel is a subset of seats with their bound lenses,
never a re-mapping. Under the legacy seat-order assignment
there is no binding to violate: the tier's seats form a
smaller panel and are tasked by the ordinary derivation
rule (a lone pre-screen seat is called once per lens,
exactly as a one-seat panel is today).

Deterministic control flow: no model calls in this module.
The plan and the trigger evaluation are pure functions of
the risk section, the derived tasks, the resolved config,
and the stage-1 reports.

With tiering unconfigured — no policy, [risk] disabled, or
`tiering` absent/false — core.run_review never consults
this module: no record section, no staged execution, the
run is byte-identical to the pre-E2 construction, which the
bench and the registered confirmation runs rely on: they
never enable it. Verification rounds are out of scope,
exactly as for E1/E3: run_verification carries no project
policy today, so there is no tiering surface there either.
"""

from __future__ import annotations

SCHEMA = "codereview.tiering/1"

# The escalation trigger kinds, in the order they are
# evaluated and recorded.
TRIGGER_BLOCKING_FINDING = "blocking finding"
TRIGGER_REVIEWER_FAILURE = "reviewer failure"
TRIGGER_LENS_UNSERVED = "lens unserved"


def tiering_config(policy):
    """The resolved tiering config carried by a loaded policy
    dict, or None when tiering is not enabled (no policy, no
    [risk] table, scoring disabled, or tiering = false) — the
    caller then runs exactly as it did before Epic E2.

    Defensive by construction, mirroring risk.risk_config:
    a hand-built policy dict with missing or mistyped values
    resolves to the defaults rather than raising mid-run; the
    validating layer is policy.load_policy (which also
    rejects tiering = true with enabled = false)."""
    if not isinstance(policy, dict):
        return None
    risk = policy.get("risk") or {}
    if not isinstance(risk, dict) \
            or not risk.get("enabled") \
            or not risk.get("tiering"):
        return None

    def _seats(key):
        value = risk.get(key)
        if not isinstance(value, (list, tuple)):
            return []
        return [name for name in value
                if isinstance(name, str) and name]

    return {
        "prescreen_seats": _seats("prescreen_seats"),
        "medium_seats": _seats("medium_seats"),
    }


def plan_stages(band, tasks, config):
    """Choose the tier's seats — the seat-level plan E4's
    escalation rule runs under.

    `tasks` is core._reviewer_tasks' output — (seat, fn,
    lens) triples in derivation order, including any
    fallback tasks run_review appended for binding-unserved
    lenses; it fixes the panel's seat order and, for the
    default medium tier, which seat first serves each lens.
    `config` is a resolved config from tiering_config. The
    caller turns the seat choice into stage task lists (a
    binding-filtered subset of `tasks`, or a fresh
    derivation for the tier's smaller panel under the
    legacy assignment — see the module docstring).

    Returns {"stage1_seats": [...], "prescreen_seats":
    [...], "medium_seats": [...] or None,
    "missing_seats": [...], "fallback_to_full": str or
    None}. On a full-panel fallback, stage1_seats is the
    whole panel and the caller runs no second stage.
    """
    config = config or {}
    panel_seats = []
    for name, _fn, _lens in tasks:
        if name not in panel_seats:
            panel_seats.append(name)

    missing = []
    fallback_to_full = None
    prescreen = list(config.get("prescreen_seats") or [])
    medium = list(config.get("medium_seats") or [])
    if band == "high":
        stage1_seats = list(panel_seats)
    elif band == "medium":
        if medium:
            for name in medium:
                if name not in panel_seats \
                        and name not in missing:
                    missing.append(name)
            stage1_seats = [n for n in panel_seats
                            if n in set(medium)]
            if not stage1_seats:
                fallback_to_full = (
                    "none of the configured medium_seats "
                    "is on the composed panel")
        else:
            # Default reduced panel: the first tasked seat
            # per lens, in task order — each lens the full
            # panel serves is served once.
            stage1_seats = []
            seen_lenses = set()
            for name, _fn, lens in tasks:
                if lens in seen_lenses:
                    continue
                seen_lenses.add(lens)
                if name not in stage1_seats:
                    stage1_seats.append(name)
    else:  # "low" (and any unexpected band: the smallest tier)
        if prescreen:
            for name in prescreen:
                if name not in panel_seats \
                        and name not in missing:
                    missing.append(name)
            stage1_seats = [n for n in panel_seats
                            if n in set(prescreen)]
            if not stage1_seats:
                fallback_to_full = (
                    "none of the configured prescreen_seats "
                    "is on the composed panel")
        else:
            stage1_seats = panel_seats[:1]
    if fallback_to_full is not None:
        stage1_seats = list(panel_seats)
    return {
        "stage1_seats": stage1_seats,
        "prescreen_seats": prescreen,
        "medium_seats": medium or None,
        "missing_seats": missing,
        "fallback_to_full": fallback_to_full,
    }


def escalation_triggers(stage1_reports, stage2_tasks,
                        blocking_sevs):
    """E4's escalation evaluation over stage 1's results.

    `stage1_reports` is the slice of the run's
    reviewer_reports the first stage produced (each a report
    dict with provider/lens/status/findings); `stage2_tasks`
    is the plan's stage-2 task list — with nothing left to
    escalate TO, no trigger can fire. `blocking_sevs` is the
    gate's blocking severity set for this run (core passes
    ("blocker",) under allow_major, else BLOCKING_DEFAULT).

    Returns a list of trigger entries {"kind", "detail"} in
    the fixed order: blocking finding, reviewer failure,
    lens unserved. Empty ⇒ the small panel's answer stands
    and stage 2 never runs. Pure: reads report dicts only.
    """
    if not stage2_tasks:
        return []
    reports = list(stage1_reports or [])
    triggers = []

    blocking = [f for r in reports
                for f in (r.get("findings") or [])
                if f.get("severity") in blocking_sevs]
    if blocking:
        triggers.append({
            "kind": TRIGGER_BLOCKING_FINDING,
            "detail": f"{len(blocking)} blocking finding(s) "
                      f"from the reduced panel "
                      f"({', '.join(sorted({f['severity'] for f in blocking}))})"})

    failed = [r for r in reports if r.get("status") == "error"]
    if failed:
        triggers.append({
            "kind": TRIGGER_REVIEWER_FAILURE,
            "detail": f"{len(failed)} reduced-panel reviewer "
                      f"job(s) ended in error "
                      f"({', '.join(sorted({r.get('provider') or '?' for r in failed}))})"})

    covered = {r.get("lens") for r in reports
               if r.get("status") == "ok"}
    stage2_lenses = []
    for _name, _fn, lens in stage2_tasks:
        if lens not in stage2_lenses:
            stage2_lenses.append(lens)
    for lens in stage2_lenses:
        if lens not in covered:
            triggers.append({
                "kind": TRIGGER_LENS_UNSERVED,
                "detail": f"lens unserved: {lens} — no "
                          f"successful reduced-panel review "
                          f"of that lens"})
    return triggers
