#!/usr/bin/env python3
"""codereview panel diversity — Epic E3 enforcement.

The check operates on the COMPOSED panel for a run — the seats
handed to core.run_review, before any of them is called — and
answers two questions:

  1. Does the panel span at least N distinct vendor families?
     (N = `[diversity] min_families` in the project policy.)
  2. If the builder's own vendor family is on the panel, can it
     be excluded without dropping the panel below that minimum?
     (Only when the policy opts in: `[diversity]
     exclude_builder_family`.)

Families come from seat metadata — the registry family tags the
seats were built with, or the operator's --seat-meta override —
never from a seat's display name. A seat whose family is
'unknown' (a fully custom spec) never counts toward the minimum:
the same convention policy.evaluate_policy applies to its
post-hoc `panel.min_families` rule. The two rules are distinct
on purpose: [diversity] judges the panel a run BRINGS (this
module, at composition); [panel] min_families judges the seats
that actually SERVED (policy.evaluate_policy, after the round).

Builder identity: run_review's `builder_family` argument is the
only input. No run path in the CLI knows the builder's family
today — a --builder-cmd is an opaque command string — so there
the exclusion simply never engages; this module never invents a
builder identity from a command line, an author string, or a
diff. When a future caller knows the family, it passes it and
the exclusion applies, recorded like everything else here.

Exclusion is a composition act, not a lens act: an excluded
seat is removed from the panel before tasks are derived, and
its lens is NEVER reassigned by this module. With an explicit
seat->lens binding, the existing S1 machinery treats the
excluded seat exactly like any absent seat — the lens is served
by its configured fallback or the run degrades with a
'lens unserved' cause. With legacy seat-order assignment, the
remaining seats fill the lenses by the ordinary rule.

Outcomes (core.run_review wires them): the assessment is
recorded verbatim in the report's `diversity` section and as an
applied `diversity.min_families` rule in the policy section. A
violation labels the run degraded with the cause
'panel diversity below minimum'. Under `[diversity] enforce =
"degrade"` (the default) that is all: the violation is recorded
as an ADVISORY policy violation and cannot change the gate.
Under `enforce = "block"` it is additionally a blocking policy
violation, gate-changing exactly like any other.

With no [diversity] configuration (or no policy at all) the
check does not run: no record section, no applied rule, no
behaviour change — byte-identical to before Epic E3.

Deterministic and pure: no model calls, no I/O. Verification
rounds are out of scope — run_verification carries no project
policy today, so there is no diversity surface there either.
"""

from __future__ import annotations

UNKNOWN_FAMILY = "unknown"


def known_families(seat_families):
    """The distinct KNOWN vendor families in a {seat: family}
    mapping, sorted. 'unknown'/empty tags never count — a panel
    of untagged seats has zero provable diversity."""
    return sorted({fam for fam in seat_families.values()
                   if fam and fam != UNKNOWN_FAMILY})


def policy_config(policy):
    """The effective [diversity] configuration of a loaded
    policy dict, or None when the check is not configured (no
    policy, no table, or the table at its defaults: minimum 0
    and exclusion off). `enforce` defaults to 'degrade'."""
    if not policy:
        return None
    div = policy.get("diversity") or {}
    min_families = div.get("min_families") or 0
    exclude = bool(div.get("exclude_builder_family"))
    if not min_families and not exclude:
        return None
    return {"min_families": int(min_families),
            "exclude_builder_family": exclude,
            "enforce": div.get("enforce") or "degrade"}


def assess_panel(seat_families, *, min_families=0,
                 builder_family=None, exclude_builder=False):
    """Assess one composed panel. `seat_families` maps seat
    name -> family tag for every seat on the panel.

    Returns the record-ready assessment:

      min_families     the configured minimum (0 = none)
      builder_family   the builder's family as given (or None)
      families_before  distinct known families, pre-exclusion
      families         distinct known families, post-exclusion
      excluded_seats   builder-family seats removed (sorted)
      builder_excluded True when exclusion actually happened
      builder_kept_reason  why exclusion did not happen, when
                       it was requested but did not apply (None
                       when it applied or was not requested, and
                       when no panel seat carries the builder's
                       family — nothing was there to keep)
      violation        families < min_families (min > 0)
      detail           the one-line verdict, used verbatim in
                       the policy violation when there is one
    """
    seats = dict(seat_families)
    families_before = known_families(seats)
    excluded = []
    kept_reason = None
    bf = str(builder_family).strip() if builder_family else None
    if exclude_builder:
        if not bf or bf == UNKNOWN_FAMILY:
            kept_reason = ("builder family unknown — exclusion "
                           "cannot apply")
        else:
            builder_seats = sorted(
                name for name, fam in seats.items() if fam == bf)
            if builder_seats:
                rest = {name: fam for name, fam in seats.items()
                        if fam != bf}
                if rest and len(known_families(rest)) \
                        >= min_families:
                    excluded = builder_seats
                    seats = rest
                elif not rest:
                    kept_reason = ("excluding the builder's "
                                   "family would empty the panel")
                else:
                    kept_reason = (
                        "excluding the builder's family would "
                        "leave the panel below the configured "
                        f"minimum of {min_families} distinct "
                        "families")
    families = known_families(seats)
    violation = min_families > 0 and len(families) < min_families
    if violation:
        detail = (
            f"composed panel spans {len(families)} distinct "
            f"vendor families ({', '.join(families) or 'none'}); "
            f"policy requires at least {min_families}")
    elif min_families > 0:
        detail = (
            f"composed panel spans {len(families)} distinct "
            f"vendor families ({', '.join(families) or 'none'}); "
            f"policy minimum of {min_families} met")
    else:
        detail = (
            f"composed panel spans {len(families)} distinct "
            f"vendor families ({', '.join(families) or 'none'}); "
            "no minimum configured")
    return {
        "min_families": int(min_families),
        "builder_family": bf,
        "families_before": families_before,
        "families": families,
        "excluded_seats": excluded,
        "builder_excluded": bool(excluded),
        "builder_kept_reason": kept_reason,
        "violation": violation,
        "detail": detail,
    }
