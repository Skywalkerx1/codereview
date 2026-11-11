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
     seats, local model servers) — the registry's default
     models are shown as SUGGESTIONS to confirm or replace,
     never as decisions. Local presets (Epic L5: ollama,
     lmstudio, or any local:<name>:<base-url>|<model>
     endpoint) are listed as their own section with the
     short recipe for each; they are keyless, so step 2
     never prompts for a key for them — there is none;
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

With `ask_mode=True` (what `codereview setup` and the first-run
prompt use; improvement plan 2026-11-11) the wizard first asks
for the REVIEW MODE — single reviewer (the default) or a
multi-reviewer panel, the user's choice whatever the project's
size — and, after the providers, which vendor's model writes the
code, so it can warn when a reviewer shares that vendor. Single
mode takes exactly one seat and skips the per-role step (the one
seat serves every role); panel mode takes two or more. Callers
that pass nothing get the earlier flow unchanged.

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


def _seat_family(spec):
    """One spec's vendor family for the wizard's warnings, or
    None when it cannot be attributed (see _panel_families)."""
    family = None
    if spec.startswith("agent:"):
        try:
            name, _opts, _cmd = _parse_agent_spec(spec)
        except ProviderError:
            return None
        family = discovery.family_for_seat_name(name)
    else:
        try:
            family = describe_spec(spec)["family"]
        except ProviderError:
            return None
    if family and family not in ("agent", "unknown"):
        return family
    return None


def _mode_step(input_fn, print_fn):
    """Ask single reviewer vs multi-reviewer panel. Enter takes
    the default (single). Bounded like the provider prompt:
    persistent nonsense aborts through the EOF channel."""
    print_fn("Review mode — your choice, for any project size:")
    print_fn("  1. single reviewer (default): one model reviews "
             "each change. Fastest and cheapest; pick a model "
             "from a different vendor than your coding agent.")
    print_fn("  2. multi-reviewer panel: two or more models from "
             "different vendors review and cross-check each "
             "other. Slower and costs more per review; catches "
             "what one vendor's models share as a blind spot.")
    for _attempt in range(MAX_PROVIDER_ATTEMPTS):
        raw = _ask(input_fn, print_fn,
                   "Review mode, 1 or 2 [1]: ").lower()
        if raw in ("", "1"):
            return "single"
        if raw == "2":
            return "panel"
        try:
            mode = registry.normalize_review_mode(raw)
        except ValueError as exc:
            print_fn(f"  ! {exc}")
            continue
        if mode:
            return mode
    print_fn("setup aborted — no review mode chosen; nothing "
             "saved.")
    raise EOFError


def _builder_step(input_fn, print_fn, providers):
    """Ask which vendor's model writes the code and warn when a
    reviewer seat shares it. Returns the family (or None when
    skipped). Never blocks: the gate's rules, not the wizard,
    decide what a review may conclude."""
    raw = _ask(input_fn, print_fn,
               "Which vendor's model writes your code? e.g. "
               "anthropic (Claude Code), openai (Codex), google "
               "(Gemini CLI), xai (Grok) — Enter to skip: ")
    builder = registry.normalize_builder_family(raw)
    if not builder:
        return None
    seat_families = {}
    for spec in providers:
        family = _seat_family(spec)
        if family:
            seat_families[spec] = family
    same = registry.same_vendor_seats(seat_families, builder)
    if same:
        print_fn(f"Same-vendor check: {', '.join(same)} "
                 f"{'is' if len(same) == 1 else 'are'} from "
                 f"{builder}, the same vendor as your coding "
                 "agent. A reviewer from the builder's own vendor "
                 "tends to share its blind spots, so this is "
                 "closer to self-review. Reviews still run; "
                 "consider a reviewer from another vendor "
                 "(re-run `codereview setup` to change it).")
    else:
        print_fn(f"Same-vendor check: no reviewer seat is from "
                 f"{builder} — good.")
    return builder


def _panel_families(providers):
    """Distinct VENDOR families a confirmed panel covers, for
    the discovery family warning. API seats read their family
    from the spec; agent seats resolve their vendor through the
    discovery table by seat name (agent:claude:* is Anthropic's
    CLI) — an agent seat the table does not know contributes no
    family, the same conservative reading the gate's derivation
    makes (its family tag is 'agent', never a guessed vendor)."""
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
               probe_fn=None, discover_fn=None, ask_mode=False):
    """Drive the wizard; returns the saved config dict
    ({"providers", "roles", "path"}), or None when aborted.
    `probe_fn(providers_dict) -> doctor-result` is optional;
    when given, the user is offered a live seat probe before
    saving (the CLI wires core.run_doctor). `discover_fn()` ->
    found-CLI list is the Epic K1 seam: None runs real PATH
    discovery against `environ`'s PATH (discovery.discover_
    clis); tests inject a fake machine. `ask_mode=True` adds
    the review-mode and same-vendor steps (module docstring)."""
    environ = os.environ if environ is None else environ
    print_fn("CodeReview setup — you choose the models; nothing "
             "is pre-picked.")
    print_fn("CodeReview is a multi-model review gate for "
             "AI-written code: a panel of models from different "
             "providers reviews every change, cross-checks each "
             "other's findings, and issues a recorded pass/block "
             "verdict — so the model that wrote the code is never "
             "the only one that checked it.")
    mode = _mode_step(input_fn, print_fn) if ask_mode else None
    picked = _discovery_step(input_fn, print_fn, environ,
                             discover_fn)
    print_fn("Providers (preset[:model], a custom "
             "name|type|base|model|KEY_ENV spec, or "
             "agent:<name>:<command>):")
    for name, preset in registry.PRESETS.items():
        if preset.get("family") == registry.LOCAL_FAMILY:
            continue  # local presets get their own section
        print_fn(f"  {name:<12} suggested model: "
                 f"{preset['model']}   key env: "
                 f"{preset['key_env']}")
    print_fn("Local model servers — they run on your own "
             "machine: no API key, and the review never "
             "leaves the machine (no network):")
    for name, preset in registry.local_presets().items():
        print_fn(f"  {name:<12} endpoint: "
                 f"{preset['base_url']}   suggested model: "
                 f"{preset['model']}")
        print_fn(f"  {'':<12} recipe: {preset['recipe']}")
    print_fn("  any other local server: "
             "local:<name>:<base-url>|<model> (e.g. "
             "local:box:http://localhost:8080/v1|my-model) — "
             "start the server, pick the spec, then probe "
             "with `codereview doctor`")
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
            problem = registry.review_mode_error(len(picked), mode)
            if problem is None:
                providers = list(picked)
                break
            print_fn(f"  ! {problem}")
            if attempts >= MAX_PROVIDER_ATTEMPTS:
                print_fn("setup aborted — too many invalid "
                         "provider entries; nothing saved.")
                raise EOFError
            continue
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
        chosen = picked + [s for s in candidates
                           if s not in picked]
        problem = registry.review_mode_error(len(chosen), mode)
        if problem:
            print_fn(f"  ! {problem}")
            if attempts >= MAX_PROVIDER_ATTEMPTS:
                print_fn("setup aborted — too many invalid "
                         "provider entries; nothing saved.")
                raise EOFError
            continue
        providers = chosen
    if mode != "single" and (picked or mode == "panel"):
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
        elif desc["family"] == registry.LOCAL_FAMILY:
                print_fn(f"  seat {desc['seat']}: local model "
                     f"server at {desc['base_url']} — no API "
                     "key; it runs on your machine, so the "
                     "review never leaves it (no network).")
        elif desc["key_env"]:
            state = ("set" if environ.get(desc["key_env"])
                     else "NOT set")
            print_fn(f"  seat {desc['seat']}: key env "
                     f"{desc['key_env']} is {state}. Export it "
                     "before running reviews; the key itself is "
                     "never stored.")
    builder_family = (_builder_step(input_fn, print_fn, providers)
                      if ask_mode else None)
    roles = {}
    # The wizard assigns the serving roles; tech-lead-shadow is
    # an opt-in evaluation seat assigned via --role or the saved
    # config, not part of the first-run flow.
    wizard_roles = [r for r in registry.ROLES
                    if r != "tech-lead-shadow"]
    if mode == "single":
        # One seat serves every lens and role; asking five role
        # questions with one possible answer is noise.
        print_fn("Single-reviewer mode: your one seat reviews "
                 "for every role (correctness, operations, "
                 "verification). A dispute with no second vendor "
                 "to adjudicate goes to you as INCONCLUSIVE.")
        wizard_roles = []
    else:
        print_fn("Assign a model per role. Enter accepts the "
                 "suggestion, type any provider spec to override, "
                 "'-' leaves the role to the panel.")
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
    # P6-06: persist the seat metadata the wizard derived
    # for the confirmed panel (each spec's family, agent
    # seats included — describe_spec resolves an agent seat
    # to its CLI's vendor family). Runs apply the saved table
    # over the derived baseline, so the families a saved
    # panel is judged by are the ones setup computed.
    seat_meta = {}
    for spec in providers:
        try:
            desc = describe_spec(spec)
        except ProviderError:
            continue
        seat_meta[desc["seat"]] = desc["family"]
    path = userconfig.save_user_config(
        providers, roles, environ=environ, seat_meta=seat_meta,
        review_mode=mode, builder_family=builder_family)
    mode_txt = ""
    if mode:
        mode_txt = ("mode: single reviewer; " if mode == "single"
                    else "mode: multi-reviewer panel; ")
    print_fn(f"Saved your setup to {path} — {mode_txt}providers: "
             f"{', '.join(providers)}; roles: "
             f"{len(roles)} assigned.")
    result = {"providers": providers, "roles": roles,
              "seat_meta": seat_meta, "path": path}
    if ask_mode:
        result["review_mode"] = mode
        result["builder_family"] = builder_family
    return result
