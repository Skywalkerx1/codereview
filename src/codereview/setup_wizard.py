#!/usr/bin/env python3
"""codereview first-run setup wizard (OpenClaw-style).

Run on first open — interactively by the review entry point
when nothing is configured, or any time via `codereview
setup`. The user, not the product, chooses the models:

  0. discovery (Epic K1): the wizard first scans PATH for the
     agent CLIs discovery.py knows and offers the found ones
     as seats — they review on the user's existing CLI logins,
     no API key needed. Discovery proposes; only a confirmed
     pick becomes a spec, indistinguishable from a hand-typed
     agent seat from then on;
  1. pick providers (registry presets, custom specs, agent
     seats) — the registry's default models are shown as
     SUGGESTIONS to confirm or replace, never as decisions;
  2. keys: for each API seat the wizard names the environment
     variable that must hold the user's key and reports whether
     it is currently set. The wizard never asks for a key value,
     never echoes one, and never writes one anywhere — the
     saved config references env var names only;
  3. assign a model per role (correctness, operations,
     verifier, tech-lead, solver): each prompt shows the
     candidate specs; the user confirms one, types another
     spec, or leaves the role to the panel;
  4. save to the user config (userconfig) as the defaults.

input/print are injectable so the whole flow is testable with
scripted answers; EOF at any prompt aborts WITHOUT saving.
"""

from __future__ import annotations

import os

from . import discovery, registry, userconfig
from .providers import (ProviderError, _parse_agent_spec,
                        describe_spec)


# Bound on provider-entry attempts in the wizard: without it
# the provider loop re-asked forever on persistently invalid
# input (review finding a509b806fda6). Exhausting the bound
# aborts through the same EOF channel as an EOF at any prompt —
# nothing is saved and the caller exits cleanly.
MAX_PROVIDER_ATTEMPTS = 3


def _ask(input_fn, print_fn, prompt):
    try:
        return input_fn(prompt).strip()
    except EOFError:
        print_fn("setup aborted — nothing saved.")
        raise


def _panel_families(providers):
    """Distinct VENDOR families a confirmed panel covers, for
    the discovery family warning. API seats read their family
    from the spec; agent seats resolve their vendor through the
    discovery table by seat name (agent:claude:* is Anthropic's
    CLI) — an agent seat the table does not know contributes no
    family, exactly the gate's own conservative reading (its
    family tag is 'agent', never a vendor)."""
    families = set()
    for spec in providers:
        family = None
        if spec.startswith("agent:"):
            try:
                name, _opts, _cmd = _parse_agent_spec(spec)
            except ProviderError:
                continue
            family = discovery.family_for_seat_name(name)
        else:
            try:
                family = describe_spec(spec)["family"]
            except ProviderError:
                continue
        if family and family not in ("agent", "unknown"):
            families.add(family)
    return families


def _discovery_step(input_fn, print_fn, environ, discover_fn):
    """Epic K1: offer the agent CLIs found on PATH as seats.

    Returns the list of agent specs the user confirmed (empty
    when nothing was found or everything was declined). Found
    CLIs without a verified seat command are reported — with
    their resolved path and probe outcome — but never offered:
    the wizard pre-fills no invocation this repository has not
    verified. EOF at the pick prompt aborts via _ask, like
    every other wizard prompt."""
    found = (discover_fn() if discover_fn is not None
             else discovery.discover_clis(environ.get("PATH")))
    if not found:
        print_fn("No supported agent CLIs found on PATH — "
                 "continuing with API providers.")
        return []
    print_fn("Agent CLIs found on this machine — they review "
             "using your existing CLI logins, no API key "
             "needed:")
    offerable = []
    for entry in found:
        if entry["probe_ok"]:
            probe_txt = "version probe ok"
            if entry["probe_detail"]:
                probe_txt += f" ({entry['probe_detail']})"
        else:
            probe_txt = ("version probe FAILED "
                         f"({entry['probe_detail']})")
        if entry["command"]:
            offerable.append(entry)
            print_fn(f"  {len(offerable)}. {entry['display']} "
                     f"— {entry['path']} ({probe_txt}) — can "
                     "be added as a seat")
        else:
            print_fn(f"  - {entry['display']} — {entry['path']} "
                     f"({probe_txt}) — found, but CodeReview "
                     "has no verified seat command for it "
                     "yet; to seat it, enter "
                     f"agent:{entry['name']}:<your command> "
                     "in the provider step below")
    if not offerable:
        return []
    raw = _ask(input_fn, print_fn,
               "Add any as seats? Numbers or names, "
               "comma-separated (Enter for none): ")
    chosen = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        entry = None
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(offerable):
                entry = offerable[idx]
        else:
            entry = next(
                (e for e in offerable
                 if e["name"] == token.lower()), None)
        if entry is None:
            print_fn(f"  ! {token!r} is not one of the "
                     "choices — ignored.")
        elif entry not in chosen:
            chosen.append(entry)
    picked = []
    for entry in chosen:
        picked.append(discovery.seat_spec(entry))
        print_fn(f"  + {entry['display']} added as an agent "
                 "seat.")
    if picked:
        print_fn("You can add API providers below too, or "
                 "press Enter at the provider prompt to keep "
                 "just the discovered seats.")
    return picked


def run_wizard(input_fn=input, print_fn=print, environ=None,
               probe_fn=None, discover_fn=None):
    """Drive the wizard; returns the saved config dict
    ({"providers", "roles", "path"}), or None when aborted.
    `probe_fn(providers_dict) -> doctor-result` is optional;
    when given, the user is offered a live seat probe before
    saving (the CLI wires core.run_doctor). `discover_fn()` ->
    found-CLI list is the Epic K1 seam: None runs real PATH
    discovery against `environ`'s PATH (discovery.discover_
    clis); tests inject a fake machine."""
    environ = os.environ if environ is None else environ
    print_fn("CodeReview setup — you choose the models; nothing "
             "is pre-picked.")
    picked = _discovery_step(input_fn, print_fn, environ,
                             discover_fn)
    print_fn("Providers (preset[:model], a custom "
             "name|type|base|model|KEY_ENV spec, or "
             "agent:<name>:<command>):")
    for name, preset in registry.PRESETS.items():
        print_fn(f"  {name:<12} suggested model: "
                 f"{preset['model']}   key env: "
                 f"{preset['key_env']}")
    providers = []
    attempts = 0
    while not providers:
        raw = _ask(input_fn, print_fn,
                   "Providers, comma-separated: ")
        attempts += 1
        candidates = [s.strip() for s in raw.split(",")
                      if s.strip()]
        if not candidates and picked:
            # Enter at the provider prompt keeps the seats the
            # discovery step confirmed — only reachable when
            # discovery contributed, so a hand-typed flow sees
            # today's behaviour byte-for-byte.
            providers = list(picked)
            break
        bad = []
        for spec in candidates:
            try:
                describe_spec(spec)
            except ProviderError as exc:
                bad.append(str(exc))
        if not candidates:
            bad.append("no providers entered")
        if bad:
            for msg in bad:
                print_fn(f"  ! {msg}")
            if attempts >= MAX_PROVIDER_ATTEMPTS:
                print_fn("setup aborted — too many invalid "
                         "provider entries; nothing saved.")
                raise EOFError
            continue
        # An exact repeat of a discovery pick (the user pasted
        # the same agent spec by hand) would seat the identical
        # command twice under two names — one model wearing
        # two seat hats. Drop exact duplicates of a pick, with
        # a note; anything else the user typed stands as typed.
        for spec in candidates:
            if spec in picked:
                print_fn(f"  ! {spec} is already in the panel "
                         "from discovery — duplicate skipped.")
        providers = picked + [s for s in candidates
                              if s not in picked]
    if picked:
        # Family-diversity guard (Epic K1): discovery makes it
        # easy to build a one-family panel without noticing.
        # Warn in plain words and offer one API spec as the
        # second family; never block saving — the gate's
        # degraded-panel rules govern what a one-family panel
        # may conclude.
        families = _panel_families(providers)
        if len(families) < 2:
            fam_txt = (f" ({', '.join(sorted(families))})"
                       if families else "")
            print_fn("Panel check: the seats above cover a "
                     f"single vendor family{fam_txt}. Reviews "
                     "still run, but the verification round "
                     "needs two distinct families to clear a "
                     "disputed finding — a one-family panel's "
                     "PASS can be held to INCONCLUSIVE.")
            extra = _ask(
                input_fn, print_fn,
                "Add an API provider from another family? "
                "Enter a provider spec (Enter to continue "
                "with this panel): ")
            if extra:
                try:
                    describe_spec(extra)
                except ProviderError as exc:
                    print_fn(f"  ! {exc} — continuing with "
                             "the current panel.")
                else:
                    if extra in providers:
                        print_fn(f"  ! {extra} is already in "
                                 "the panel — duplicate "
                                 "skipped.")
                    else:
                        providers.append(extra)
    for spec in providers:
        desc = describe_spec(spec)
        if desc["kind"] == "agent":
            print_fn(f"  seat {desc['seat']}: agent seat — it "
                     "authenticates as itself, no key env.")
        elif desc["key_env"]:
            state = ("set" if environ.get(desc["key_env"])
                     else "NOT set")
            print_fn(f"  seat {desc['seat']}: key env "
                     f"{desc['key_env']} is {state}. Export it "
                     "before running reviews; the key itself is "
                     "never stored.")
    print_fn("Assign a model per role. Enter accepts the "
             "suggestion, type any provider spec to override, "
             "'-' leaves the role to the panel.")
    roles = {}
    # The wizard assigns the serving roles; tech-lead-shadow is
    # an opt-in evaluation seat assigned via --role or the saved
    # config, not part of the first-run flow.
    wizard_roles = [r for r in registry.ROLES
                    if r != "tech-lead-shadow"]
    for i, role in enumerate(wizard_roles):
        suggestion = providers[i % len(providers)]
        answer = _ask(
            input_fn, print_fn,
            f"  {role} [{suggestion}]: ")
        if answer == "-":
            continue
        spec = answer or suggestion
        try:
            describe_spec(spec)
        except ProviderError as exc:
            print_fn(f"  ! {exc} — role left to the panel.")
            continue
        roles[role] = spec
    if probe_fn is not None:
        answer = _ask(input_fn, print_fn,
                      "Probe the seats now? [y/N]: ")
        if answer.lower().startswith("y"):
            from .providers import build_providers
            try:
                result = probe_fn(build_providers(providers))
                for seat in result.get("seats") or []:
                    print_fn(f"  probe {seat.get('name')}: "
                             f"{'ok' if seat.get('ok') else 'FAILED'}")
            except Exception as exc:  # noqa: BLE001
                print_fn(f"  probe failed: {exc}")
    path = userconfig.save_user_config(providers, roles,
                                       environ=environ)
    print_fn(f"Saved your setup to {path} — providers: "
             f"{', '.join(providers)}; roles: "
             f"{len(roles)} assigned.")
    return {"providers": providers, "roles": roles,
            "path": path}
