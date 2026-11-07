#!/usr/bin/env python3
"""codereview provider registry — the catalogue of supported LLM
providers and the per-role model-assignment surface.

One source of truth for every preset: wire kind, base URL, default
model, the environment variable the user's OWN key is read from
(BYOK — keys are never stored, logged, or shipped with the tool),
the vendor FAMILY tag (the independence checks in core — cross-
family confirmation and the Tech Lead's family-distinctness rule —
read family from here, never from a seat's display name), default
extra payload, and per-model request quirks.

Wire kinds:
  openai-compatible — POST {base}/chat/completions, Bearer auth.
      Most vendors now expose this shape (OpenAI, DeepSeek,
      MiniMax, Moonshot/Kimi, NVIDIA NIM, xAI, Mistral,
      OpenRouter), which is why new majors are one registry row.
  gemini — the native generateContent API (Google).
  anthropic — the native Messages API (x-api-key + version header,
      content-block response).

Spec grammar (consumed by providers.build_provider):
  preset                — registry default model
  preset:model          — registry endpoint, caller's model
  name|type|base|model|KEY_ENV   — fully custom seat (type is
                          openai-compatible, gemini, or anthropic)
  openai-compatible:<base>|<model>|<KEY_ENV> — generic escape
                          hatch for any other compatible endpoint
  agent:<name>:<command> — a local agent CLI seat (providers.py)
  local:<name>:<base-url>|<model> — a named LOCAL model server
                          (Epic L5): any OpenAI-compatible
                          endpoint the user runs on their own
                          machine; keyless (no API key, no
                          key env), family tag 'local'. The
                          named local presets below (ollama,
                          lmstudio) are this form with the
                          conventional endpoint pre-filled.

Roles (owner directive 2026-11-04: the user picks the model for
each role): correctness, operations (the two review lenses),
verifier (the verification-round panel), tech-lead (the dispute
adjudicator seat — its family must stay distinct from the finding's
raiser and refuter; the registry family tags feed that check), and
solver (intake mode). Assignment syntax everywhere is
`--role <role>=<provider-spec>`, repeatable; nothing assigned =
today's behaviour exactly.
"""

from __future__ import annotations

# role -> the lens it pins, where the role IS a review lens.
ROLES = ("correctness", "operations", "verifier", "tech-lead",
         "tech-lead-shadow", "solver")
LENS_ROLES = {"correctness": "correctness",
              "operations": "operations"}

# Each preset:
#   kind          wire kind (see module docstring)
#   base_url      API base (None for the gemini native shape, whose
#                 URL embeds the model)
#   model         default model suggestion — a starting point, the
#                 user overrides with preset:model or a custom spec
#   key_env       env var holding the USER's key for this provider
#                 (None for the keyless local presets, Epic L5:
#                 a local server needs no credential and none is
#                 ever read, sent, or prompted for)
#   family        vendor family tag for independence checks
#   extra         extra payload fields merged into every request
#   no_temperature  model-name prefixes whose API rejects a
#                 caller-set temperature (the gpt-5 lesson: HTTP
#                 400 on temperature != default) — for those models
#                 the field is OMITTED, never faked
#   completion_tokens  model-name prefixes whose API rejects
#                 `max_tokens` and requires `max_completion_tokens`
#                 instead (the second gpt-5 lesson, from the L3
#                 smoke: the openai preset's default gpt-5-mini
#                 answered HTTP 400 to every CLI request because
#                 the payload carried max_tokens) — for those
#                 models the token cap is sent under the new name
#   recipe        (local presets only) the short operator recipe
#                 the setup wizard prints: start the server, then
#                 pick the preset, then probe with `doctor`
PRESETS = {
    "openai": {
        "kind": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "key_env": "OPENAI_API_KEY",
        "family": "openai",
        "extra": None,
        "no_temperature": ("gpt-5", "o1", "o3", "o4"),
        "completion_tokens": ("gpt-5", "o1", "o3", "o4"),
    },
    "gemini": {
        "kind": "gemini",
        "base_url": None,
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
        "family": "google",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "family": "anthropic",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "deepseek": {
        "kind": "openai-compatible",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "family": "deepseek",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "minimax": {
        "kind": "openai-compatible",
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-M2",
        "key_env": "MINIMAX_API_KEY",
        "family": "minimax",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "moonshot": {
        "kind": "openai-compatible",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2-0711-preview",
        "key_env": "MOONSHOT_API_KEY",
        "family": "moonshot",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "nvidia": {
        "kind": "openai-compatible",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "key_env": "NVIDIA_API_KEY",
        "family": "nvidia",
        "extra": {"chat_template_kwargs": {"enable_thinking": False}},
        "no_temperature": (),
        "completion_tokens": (),
    },
    "xai": {
        "kind": "openai-compatible",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-mini",
        "key_env": "XAI_API_KEY",
        "family": "xai",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "mistral": {
        "kind": "openai-compatible",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
        "key_env": "MISTRAL_API_KEY",
        "family": "mistral",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    "openrouter": {
        "kind": "openai-compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-sonnet-4.5",
        "key_env": "OPENROUTER_API_KEY",
        # The router is its own family tag: the MODEL behind a
        # routed seat varies, so independence checks treat an
        # OpenRouter seat as family 'openrouter' and users who need
        # a stricter reading tag the seat with --seat-meta.
        "family": "openrouter",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
    },
    # Local model servers (Epic L5): first-class presets for
    # endpoints the user runs on their own machine. Keyless by
    # construction (key_env None — providers.py sends no
    # Authorization header and reads no credential), family
    # 'local' for the independence checks (a local seat never
    # counts as a second VENDOR family), and the endpoints are
    # the servers' conventional loopback defaults — a preset
    # names an endpoint, never a panel: which model serves is
    # still the user's pick (preset:model), exactly like the
    # hosted presets.
    "ollama": {
        "kind": "openai-compatible",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "key_env": None,
        "family": "local",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
        "recipe": "start Ollama (`ollama serve`, or open the "
                  "Ollama app) and pull a model (`ollama pull "
                  "<model>`), then pick this preset and run "
                  "`codereview doctor` to probe the seat",
    },
    "lmstudio": {
        "kind": "openai-compatible",
        "base_url": "http://localhost:1234/v1",
        "model": "local-model",
        "key_env": None,
        "family": "local",
        "extra": None,
        "no_temperature": (),
        "completion_tokens": (),
        "recipe": "open LM Studio, load a model, and start its "
                  "local server (Developer tab; default port "
                  "1234), then pick this preset and run "
                  "`codereview doctor` to probe the seat",
    },
}

WIRE_KINDS = ("openai-compatible", "gemini", "anthropic")

# The family tag every local seat carries (Epic L5): local
# endpoints are the user's own machines, not a vendor, so the
# independence checks see one honest tag — two local seats are
# never two independent families, and a local seat never stands
# in for a hosted vendor's family.
LOCAL_FAMILY = "local"

# Prefix of the named-local-endpoint spec form:
# local:<name>:<base-url>|<model> (providers.describe_spec is
# the parser; this is the shared spelling).
LOCAL_SPEC_PREFIX = "local:"


def is_local_preset(name):
    """True for a registry preset that is a local model server
    (Epic L5): keyless, loopback endpoint, family 'local'."""
    preset = PRESETS.get(name or "")
    return bool(preset) and preset.get("family") == LOCAL_FAMILY


def local_presets():
    """{name: preset} for the local presets, in registry
    order — the setup wizard lists these as their own section,
    apart from the hosted (keyed) providers."""
    return {name: p for name, p in PRESETS.items()
            if p.get("family") == LOCAL_FAMILY}


def omit_temperature(preset_name, model):
    """True when the preset's quirk table says this model rejects a
    caller-set temperature and the field must be omitted."""
    preset = PRESETS.get(preset_name or "", {})
    prefixes = preset.get("no_temperature") or ()
    return any(str(model).startswith(p) for p in prefixes)


def completion_tokens(preset_name, model):
    """True when the preset's quirk table says this model rejects
    `max_tokens` and the token cap must be sent as
    `max_completion_tokens` (OpenAI's gpt-5 / o-series lines)."""
    preset = PRESETS.get(preset_name or "", {})
    prefixes = preset.get("completion_tokens") or ()
    return any(str(model).startswith(p) for p in prefixes)


def parse_role_assignments(values):
    """--role values -> {role: provider-spec}.

    Validates role names against ROLES and rejects a role assigned
    twice (a silent last-wins would hide a configuration mistake).
    Raises ValueError with an operator-readable message."""
    roles = {}
    for value in values or []:
        role, eq, spec = str(value).partition("=")
        role, spec = role.strip().lower(), spec.strip()
        if not eq or role not in ROLES or not spec:
            raise ValueError(
                f"bad --role {value!r}: want <role>=<provider-spec> "
                f"with role one of {', '.join(ROLES)}")
        if role in roles:
            raise ValueError(
                f"role {role!r} assigned twice ({roles[role]!r} and "
                f"{spec!r}); assign each role once")
        roles[role] = spec
    return roles
