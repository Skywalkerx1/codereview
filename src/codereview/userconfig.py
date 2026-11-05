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
    providers = [str(p) for p in data.get("providers") or []]
    roles = {str(k): str(v)
             for k, v in (data.get("roles") or {}).items()}
    return {"providers": providers, "roles": roles,
            "path": path}


def _toml_str(value):
    # JSON strings are valid TOML basic strings for the content
    # specs contain (URLs, names, commands without control chars).
    return json.dumps(str(value), ensure_ascii=False)


def save_user_config(providers, roles, environ=None):
    """Write the setup file (specs only — never a key value) and
    return its path."""
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
