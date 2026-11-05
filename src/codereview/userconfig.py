#!/usr/bin/env python3
"""codereview user setup — the per-user config the FIRST RUN
creates (owner directive 2026-11-04: "we don't choose the LLM
model for them").

The product ships NO default panel. On first open the user runs
the setup wizard (`codereview setup`), picks their providers,
points at their own keys, assigns a model per role, and saves
THAT as their defaults. This module is the storage half:

  path    $CODEREVIEW_CONFIG, else $XDG_CONFIG_HOME/codereview/
          config.toml, else ~/.config/codereview/config.toml
  content provider SPECS and role -> spec assignments only.
          A spec names a key ENVIRONMENT VARIABLE (the custom
          spec grammar) or a registry preset (whose key env the
          registry names) — key VALUES never appear here, are
          never prompted into the file, and are never echoed.

Resolution order at run time (cli): explicit --provider/--role
flags, then $CODEREVIEW_PROVIDERS, then this config. Nothing
else. A run with none of those is "not set up" and stops with
instructions — it never falls back to a built-in panel.
"""

from __future__ import annotations

import json
import os
import tomllib


def config_path(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("CODEREVIEW_CONFIG", "").strip()
    if override:
        return override
    xdg = environ.get("XDG_CONFIG_HOME", "").strip()
    base = xdg or os.path.join(environ.get("HOME", "~"), ".config")
    return os.path.join(base, "codereview", "config.toml")


def load_user_config(environ=None):
    """-> {"providers": [...], "roles": {role: spec}} or None
    when no setup exists. A malformed config raises ValueError —
    a broken setup must be loud, never silently ignored."""
    path = config_path(environ)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(
                f"user config {path} is not valid TOML: {exc}")
    # Type-validate before iterating (open-refutations
    # hardening, 9a4415ddafa6): a non-list `providers` was
    # iterated element-wise (a string silently became one
    # "provider" per character) and a non-table `roles` raised
    # an uncaught AttributeError from .items() — both break
    # this function's documented contract that a malformed
    # config raises ValueError naming the path.
    raw_providers = data.get("providers")
    if raw_providers is None:
        raw_providers = []
    if not isinstance(raw_providers, list):
        raise ValueError(
            f"user config {path}: 'providers' must be a list "
            f"of provider specs, got "
            f"{type(raw_providers).__name__}")
    raw_roles = data.get("roles")
    if raw_roles is None:
        raw_roles = {}
    if not isinstance(raw_roles, dict):
        raise ValueError(
            f"user config {path}: 'roles' must be a table of "
            f"role = \"spec\" entries, got "
            f"{type(raw_roles).__name__}")
    providers = [str(p) for p in raw_providers]
    roles = {str(k): str(v) for k, v in raw_roles.items()}
    # Epic K3a: the optional [hosting] table — today one key,
    # `herdr`, a list of SEAT NAMES whose agent seats run
    # inside herdr panes when herdr is present (see
    # herdrhost.py). It is a hosting hint in the saved config
    # only: never part of the agent: spec grammar, so records
    # written before hosting existed stay valid. Type-
    # validated like the rest — a malformed table is a loud
    # ValueError, never a silently ignored hint.
    raw_hosting = data.get("hosting")
    if raw_hosting is None:
        raw_hosting = {}
    if not isinstance(raw_hosting, dict):
        raise ValueError(
            f"user config {path}: 'hosting' must be a table "
            f"of hosting hints, got "
            f"{type(raw_hosting).__name__}")
    raw_herdr = raw_hosting.get("herdr")
    if raw_herdr is None:
        raw_herdr = []
    if not isinstance(raw_herdr, list):
        raise ValueError(
            f"user config {path}: 'hosting.herdr' must be a "
            f"list of seat names, got "
            f"{type(raw_herdr).__name__}")
    hosting = {"herdr": [str(s) for s in raw_herdr]}
    return {"providers": providers, "roles": roles,
            "hosting": hosting, "path": path}


def _toml_str(value):
    # JSON strings are valid TOML basic strings for the content
    # specs contain (URLs, names, commands without control chars).
    return json.dumps(str(value), ensure_ascii=False)


def save_user_config(providers, roles, environ=None,
                     hosting=None):
    """Write the setup file (specs only — never a key value) and
    return its path. `hosting` ({"herdr": [seat names]}) adds
    the [hosting] table; the default None writes exactly the
    bytes earlier versions wrote, so an unchanged setup stays
    byte-identical."""
    path = config_path(environ)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# CodeReview user setup — created by `codereview setup`.",
        "# Provider specs and role assignments only: keys live in",
        "# the environment variables the specs name, never here.",
        "providers = [" + ", ".join(
            _toml_str(p) for p in providers) + "]",
        "",
        "[roles]",
    ]
    for role in sorted(roles):
        lines.append(f"{role} = {_toml_str(roles[role])}")
    herdr_seats = list((hosting or {}).get("herdr") or [])
    if herdr_seats:
        lines += [
            "",
            "[hosting]",
            "# Agent seats listed here run inside herdr panes "
            "when herdr",
            "# is present (Epic K3a); without herdr they run "
            "headless.",
            "herdr = [" + ", ".join(
                _toml_str(s) for s in herdr_seats) + "]",
        ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def env_provider_specs(environ=None):
    environ = os.environ if environ is None else environ
    env = (environ.get("CODEREVIEW_PROVIDERS")
           or environ.get("REVIEWLOOP_PROVIDERS", ""))
    return [s.strip() for s in env.split(",") if s.strip()]


def default_provider_specs(environ=None):
    """The run's provider specs when the user passed none:
    environment first, then the saved setup. Empty list means
    NOT SET UP — the caller stops with instructions rather than
    inventing a panel."""
    specs = env_provider_specs(environ)
    if specs:
        return specs
    cfg = load_user_config(environ)
    if cfg and cfg["providers"]:
        return list(cfg["providers"])
    return []


def default_role_assignments(environ=None):
    """Saved role -> spec assignments from the user config
    ({} when no setup exists). Explicit --role flags override
    these per role at the CLI seam."""
    cfg = load_user_config(environ)
    return dict(cfg["roles"]) if cfg else {}


def default_hosting_herdr_seats(environ=None):
    """Seat names the saved setup marks for herdr pane hosting
    (Epic K3a; [] when no setup or no [hosting] table)."""
    cfg = load_user_config(environ)
    if not cfg:
        return []
    return list((cfg.get("hosting") or {}).get("herdr") or [])


NOT_SET_UP = (
    "codereview is not set up yet: no providers were given and "
    "no saved setup exists.\n"
    "  Interactive:  run `codereview setup` and pick your "
    "providers, keys, and per-role models.\n"
    "  Scripted:     pass --provider <spec> (repeatable), or set "
    "$CODEREVIEW_PROVIDERS, or run `codereview setup` once on "
    "this machine.\n"
    "CodeReview ships no default panel — the models are yours "
    "to choose.")
