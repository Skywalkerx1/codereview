#!/usr/bin/env python3
"""codereview first-run setup wizard (OpenClaw-style).

Run on first open — interactively by the review entry point
when nothing is configured, or any time via `codereview
setup`. The user, not the product, chooses the models:

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

from . import registry, userconfig
from .providers import ProviderError, describe_spec


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


def run_wizard(input_fn=input, print_fn=print, environ=None,
               probe_fn=None):
    """Drive the wizard; returns the saved config dict
    ({"providers", "roles", "path"}), or None when aborted.
    `probe_fn(providers_dict) -> doctor-result` is optional;
    when given, the user is offered a live seat probe before
    saving (the CLI wires core.run_doctor)."""
    environ = os.environ if environ is None else environ
    print_fn("CodeReview setup — you choose the models; nothing "
             "is pre-picked.")
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
        providers = candidates
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
