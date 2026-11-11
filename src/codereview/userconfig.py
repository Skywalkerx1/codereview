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
          The wizard also saves the seat metadata it derived
          for the panel (P6-06: [seat_meta], seat name ->
          vendor family) so a saved panel's families are the
          ones setup computed, not a later re-derivation.

Resolution order at run time (cli): explicit --provider/--role
flags, then $CODEREVIEW_PROVIDERS, then this config. Nothing
else. A run with none of those is "not set up" and stops with
instructions — it never falls back to a built-in panel.
"""

from __future__ import annotations

import json
import os
import re
import tomllib

from . import registry


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
    # Epic L4: the optional [notify] table — one key,
    # `command`, the argv of the operator's local attention
    # command (see notify.py). It lives HERE, in the user
    # setup, by design: notifications are operator preference,
    # never project contract, so the project policy has no
    # notify key (policy.load_policy rejects the table).
    # Type-validated like the rest — a malformed table is a
    # loud ValueError, never a silently ignored command.
    raw_notify = data.get("notify")
    if raw_notify is None:
        raw_notify = {}
    if not isinstance(raw_notify, dict):
        raise ValueError(
            f"user config {path}: 'notify' must be a table "
            f"of notification settings, got "
            f"{type(raw_notify).__name__}")
    raw_command = raw_notify.get("command")
    if raw_command is None:
        raw_command = []
    if not isinstance(raw_command, list) or not all(
            isinstance(c, str) for c in raw_command):
        raise ValueError(
            f"user config {path}: 'notify.command' must be a "
            f"list of strings (the notify command's argv), "
            f"got {raw_command!r}")
    notify = {"command": [str(c) for c in raw_command]}
    # P6-06: the optional [seat_meta] table — seat name ->
    # vendor family, written by the setup wizard from the
    # metadata it derived for the confirmed panel. The CLI
    # applies it over the derived baseline (explicit
    # --seat-meta still wins). Type-validated like the rest.
    raw_seat_meta = data.get("seat_meta")
    if raw_seat_meta is None:
        raw_seat_meta = {}
    if not isinstance(raw_seat_meta, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in raw_seat_meta.items()):
        raise ValueError(
            f"user config {path}: 'seat_meta' must be a "
            f"table of seat name = \"family\" entries, got "
            f"{raw_seat_meta!r}")
    seat_meta = {str(k): str(v)
                 for k, v in raw_seat_meta.items()}
    # Improvement plan 2026-11-11: the optional top-level
    # `review_mode` ("single" or "panel") and `builder_family`
    # (the coding agent's vendor, for the same-vendor warning)
    # the setup wizard saves. Absent = the pre-mode behaviour.
    # Type- and shape-validated like the rest: a saved single
    # mode with more than one provider (or a panel with fewer
    # than two) is a broken setup and fails loudly.
    raw_mode = data.get("review_mode")
    if raw_mode is not None and not isinstance(raw_mode, str):
        raise ValueError(
            f"user config {path}: 'review_mode' must be a "
            f"string, got {type(raw_mode).__name__}")
    try:
        review_mode = registry.normalize_review_mode(raw_mode)
    except ValueError as exc:
        raise ValueError(f"user config {path}: {exc}")
    if review_mode and providers:
        problem = registry.review_mode_error(len(providers),
                                             review_mode)
        if problem:
            raise ValueError(f"user config {path}: {problem} "
                             f"(re-run `codereview setup`)")
    raw_builder = data.get("builder_family")
    if raw_builder is not None and not isinstance(raw_builder,
                                                  str):
        raise ValueError(
            f"user config {path}: 'builder_family' must be a "
            f"string, got {type(raw_builder).__name__}")
    builder_family = registry.normalize_builder_family(raw_builder)
    return {"providers": providers, "roles": roles,
            "hosting": hosting, "notify": notify,
            "seat_meta": seat_meta, "review_mode": review_mode,
            "builder_family": builder_family, "path": path}


def _toml_str(value):
    # JSON strings are valid TOML basic strings for the content
    # specs contain (URLs, names, commands without control chars).
    return json.dumps(str(value), ensure_ascii=False)


def _toml_key(name):
    # Bare TOML keys are [A-Za-z0-9_-]+; anything else is
    # written as a quoted key.
    if re.fullmatch(r"[A-Za-z0-9_-]+", str(name)):
        return str(name)
    return _toml_str(name)


def save_user_config(providers, roles, environ=None,
                     hosting=None, notify=None, seat_meta=None,
                     review_mode=None, builder_family=None):
    """Write the setup file (specs only — never a key value) and
    return its path. `hosting` ({"herdr": [seat names]}) adds
    the [hosting] table; `notify` ({"command": [argv...]})
    adds the [notify] table (Epic L4); `seat_meta`
    ({seat name: family}) adds the [seat_meta] table (P6-06);
    `review_mode` ("single" / "panel") and `builder_family`
    add top-level keys (improvement plan 2026-11-11); the
    defaults write exactly the bytes earlier versions wrote,
    so an unchanged setup stays byte-identical."""
    path = config_path(environ)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# CodeReview user setup — created by `codereview setup`.",
        "# Provider specs and role assignments only: keys live in",
        "# the environment variables the specs name, never here.",
        "providers = [" + ", ".join(
            _toml_str(p) for p in providers) + "]",
    ]
    # Top-level keys must precede the first table in TOML.
    if review_mode:
        lines.append("review_mode = " + _toml_str(
            registry.normalize_review_mode(review_mode)))
    if builder_family:
        lines.append("builder_family = " + _toml_str(
            registry.normalize_builder_family(builder_family)))
    lines += [
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
    notify_command = list((notify or {}).get("command") or [])
    if notify_command:
        lines += [
            "",
            "[notify]",
            "# Attention notifications (Epic L4): this local "
            "command is",
            "# run with the event name and a one-line summary "
            "appended",
            "# when a seat blocks or the gate reaches a "
            "verdict.",
            "command = [" + ", ".join(
                _toml_str(c) for c in notify_command) + "]",
        ]
    seat_meta = dict(seat_meta or {})
    if seat_meta:
        lines += [
            "",
            "[seat_meta]",
            "# Seat metadata the setup wizard derived for "
            "this panel",
            "# (P6-06): each seat's vendor family. Runs apply "
            "it over",
            "# the derived baseline; --seat-meta overrides it "
            "per seat.",
        ]
        for name in sorted(seat_meta):
            lines.append(
                f"{_toml_key(name)} = "
                f"{_toml_str(seat_meta[name])}")
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


def default_seat_meta(environ=None):
    """The saved setup's [seat_meta] table ({seat name:
    family}; {} when no setup or no table)."""
    cfg = load_user_config(environ)
    if not cfg:
        return {}
    return dict(cfg.get("seat_meta") or {})


def default_review_mode(environ=None):
    """The saved setup's review mode ("single" / "panel"), or
    None when no setup exists or it predates modes."""
    cfg = load_user_config(environ)
    return (cfg or {}).get("review_mode")


def default_builder_family(environ=None):
    """The saved setup's coding-agent vendor family, or None."""
    cfg = load_user_config(environ)
    return (cfg or {}).get("builder_family")


def default_notify_command(environ=None):
    """The saved setup's [notify] command argv (Epic L4; []
    when no setup or no [notify] table). The ONLY source of a
    notify command: the project policy cannot set one."""
    cfg = load_user_config(environ)
    if not cfg:
        return []
    return list((cfg.get("notify") or {}).get("command") or [])


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
