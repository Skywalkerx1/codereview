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
#   family        vendor family tag for independence checks
#   extra         extra payload fields merged into every request
#   no_temperature  model-name prefixes whose API rejects a
#                 caller-set temperature (the gpt-5 lesson: HTTP
#                 400 on temperature != default) — for those models
#                 the field is OMITTED, never faked
PRESETS = {
    "openai": {
        "kind": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "key_env": "OPENAI_API_KEY",
        "family": "openai",
        "extra": None,
        "no_temperature": ("gpt-5", "o1", "o3", "o4"),
    },
    "gemini": {
        "kind": "gemini",
        "base_url": None,
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
        "family": "google",
        "extra": None,
        "no_temperature": (),
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "family": "anthropic",
        "extra": None,
        "no_temperature": (),
    },
    "deepseek": {
        "kind": "openai-compatible",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "family": "deepseek",
        "extra": None,
        "no_temperature": (),
    },
    "minimax": {
        "kind": "openai-compatible",
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-M2",
        "key_env": "MINIMAX_API_KEY",
        "family": "minimax",
        "extra": None,
        "no_temperature": (),
    },
    "moonshot": {
        "kind": "openai-compatible",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2-0711-preview",
        "key_env": "MOONSHOT_API_KEY",
        "family": "moonshot",
        "extra": None,
        "no_temperature": (),
    },
    "nvidia": {
        "kind": "openai-compatible",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "key_env": "NVIDIA_API_KEY",
        "family": "nvidia",
        "extra": {"chat_template_kwargs": {"enable_thinking": False}},
        "no_temperature": (),
    },
    "xai": {
        "kind": "openai-compatible",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-mini",
        "key_env": "XAI_API_KEY",
        "family": "xai",
        "extra": None,
        "no_temperature": (),
    },
    "mistral": {
        "kind": "openai-compatible",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
        "key_env": "MISTRAL_API_KEY",
        "family": "mistral",
        "extra": None,
        "no_temperature": (),
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
    },
}

WIRE_KINDS = ("openai-compatible", "gemini", "anthropic")


def omit_temperature(preset_name, model):
    """True when the preset's quirk table says this model rejects a
    caller-set temperature and the field must be omitted."""
    preset = PRESETS.get(preset_name or "", {})
    prefixes = preset.get("no_temperature") or ()
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
