#!/usr/bin/env python3
"""reviewloop providers — build reviewer callables from API keys.

A provider is a callable: prompt (str) -> raw model text (str).
Keys are read from environment variables only; nothing is stored,
logged, or written to disk by this module. Redirects are refused on
authenticated requests.

Presets: gemini, openai, xai, nvidia, deepseek.
Custom:  name|openai-compatible|https://base.url/v1|model|KEY_ENV
         name|gemini|-|model|KEY_ENV
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 240


class ProviderError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ProviderError("redirect refused on authenticated request")


def _post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code} from {url.split('/')[2]}") from e
    except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
        raise ProviderError(f"network error: {e}") from e


def _key(key_env):
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise ProviderError(f"{key_env} is not set")
    return key


_SYSTEM = ("You are an independent, strict code reviewer in a multi-model "
           "review loop. Output only the JSON object the user prompt "
           "asks for.")


def openai_compatible(base_url, model, key_env, extra_payload=None):
    """Callable for any OpenAI-compatible chat completions endpoint."""
    def call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 8192,
        }
        if extra_payload:
            payload.update(extra_payload)
        data = _post_json(
            base_url.rstrip("/") + "/chat/completions",
            {"Authorization": f"Bearer {_key(key_env)}"}, payload)
        try:
            text = (data["choices"][0]["message"].get("content")
                    or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
        return text
    return call


def gemini(model, key_env="GEMINI_API_KEY"):
    """Callable for the Gemini generateContent API."""
    def call(prompt):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1, "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }
        data = _post_json(url, {"x-goog-api-key": _key(key_env)}, payload)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
        return text
    return call


PRESETS = {
    "gemini": ("gemini", None, "gemini-2.5-flash", "GEMINI_API_KEY", None),
    "openai": ("openai-compatible", "https://api.openai.com/v1",
               "gpt-5-mini", "OPENAI_API_KEY", None),
    "xai": ("openai-compatible", "https://api.x.ai/v1",
            "grok-4-mini", "XAI_API_KEY", None),
    "nvidia": ("openai-compatible", "https://integrate.api.nvidia.com/v1",
               "nvidia/nemotron-3.5-lightning-30b-a3b", "NVIDIA_API_KEY",
               {"chat_template_kwargs": {"enable_thinking": False}}),
    "deepseek": ("openai-compatible", "https://api.deepseek.com",
                 "deepseek-chat", "DEEPSEEK_API_KEY", None),
}


def build_provider(spec):
    """spec -> (name, callable). See module docstring for formats."""
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
    else:
        name = spec.strip().lower()
        if name not in PRESETS:
            raise ProviderError(
                f"unknown provider {spec!r}; presets: "
                f"{', '.join(sorted(PRESETS))}, or use the custom "
                "name|type|base_url|model|key_env form")
        kind, base, model, key_env, extra = PRESETS[name]
        if kind == "gemini":
            return name, gemini(model, key_env)
        return name, openai_compatible(base, model, key_env, extra)
    if kind == "gemini":
        return name, gemini(model, key_env)
    if kind == "openai-compatible":
        return name, openai_compatible(base, model, key_env)
    raise ProviderError(f"unknown provider type {kind!r}")


def build_providers(specs):
    providers = {}
    for spec in specs:
        name, fn = build_provider(spec)
        providers[name] = fn
    return providers
