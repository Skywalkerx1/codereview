#!/usr/bin/env python3
"""codereview providers — build reviewer callables from API keys.

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

_SOLVER_SYSTEM = ("You are the solver in a software-maintenance "
                  "workflow. You turn an issue report into an "
                  "executable solution plan in Markdown. You never "
                  "write the fix yourself; a builder implements your "
                  "plan and an independent review gates the result.")


def openai_compatible(base_url, model, key_env, extra_payload=None,
                      system=_SYSTEM):
    """Callable for any OpenAI-compatible chat completions endpoint."""
    def call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
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


def gemini(model, key_env="GEMINI_API_KEY", system=_SYSTEM,
           json_mode=True):
    """Callable for the Gemini generateContent API.

    json_mode (the reviewer default) asks the API for a JSON body;
    solver callables pass json_mode=False because their answer is a
    Markdown plan, not a JSON object."""
    def call(prompt):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        generation = {"temperature": 0.1, "maxOutputTokens": 8192}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation,
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


def build_provider(spec, occurrence=1, text_mode=False):
    """spec -> (name, callable, account_label).

    `occurrence` > 1 (the same seat requested again) selects the
    next account's key env for presets: GEMINI_API_KEY_2, _3, ...

    `text_mode` builds a solver callable instead of a reviewer: a
    solver-persona system prompt and, for Gemini, no JSON response
    mode — the answer is a Markdown plan."""
    system = _SOLVER_SYSTEM if text_mode else _SYSTEM
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
        if kind == "gemini":
            return name, gemini(model, key_env, system=system,
                                json_mode=not text_mode), key_env
        if kind == "openai-compatible":
            return name, openai_compatible(base, model, key_env,
                                           system=system), key_env
        raise ProviderError(f"unknown provider type {kind!r}")
    name = spec.strip().lower()
    if name not in PRESETS:
        raise ProviderError(
            f"unknown provider {spec!r}; presets: "
            f"{', '.join(sorted(PRESETS))}, or use the custom "
            "name|type|base_url|model|key_env form")
    kind, base, model, key_env, extra = PRESETS[name]
    if occurrence > 1:
        key_env = f"{key_env}_{occurrence}"
    if kind == "gemini":
        return name, gemini(model, key_env, system=system,
                            json_mode=not text_mode), key_env
    return name, openai_compatible(base, model, key_env, extra,
                                   system=system), key_env


_RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "401", "403",
                      "quota", "rate limit", "network", "timed out",
                      "timeout")


def is_retryable(exc):
    """Quota / availability / dead-key errors are worth rotating to
    the next account for; a malformed request is not."""
    msg = str(exc).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


class AccountPool:
    """One reviewer seat backed by several accounts, tried in order.

    On a retryable error (quota, rate limit, 5xx, dead key) the next
    account takes the seat. Every rotation is recorded on
    `rotations` and the serving account on `last_account`, so run
    reports show exactly which account reviewed and when a switch
    happened — never a silent substitution. Account labels are key
    env names, never key values."""

    def __init__(self, accounts):
        # accounts: [(label, callable)]
        self.accounts = list(accounts)
        self.rotations = []
        self.last_account = None
        import threading
        self._lock = threading.Lock()

    def __call__(self, prompt):
        last_exc = None
        for i, (label, fn) in enumerate(self.accounts):
            try:
                text = fn(prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not is_retryable(exc):
                    raise
                if i + 1 < len(self.accounts):
                    with self._lock:
                        self.rotations.append({
                            "from": label,
                            "to": self.accounts[i + 1][0],
                            "error": str(exc)[:200]})
                continue
            with self._lock:
                self.last_account = label
            return text
        raise last_exc


def build_providers(specs, text_mode=False):
    """specs -> {seat name: callable}. Repeating a seat (the same
    preset twice, or custom specs sharing a name) builds an
    AccountPool for that seat with one account per occurrence."""
    seats = {}
    counts = {}
    for spec in specs:
        seat_key = spec.split("|")[0].strip().lower() \
            if "|" in spec else spec.strip().lower()
        counts[seat_key] = counts.get(seat_key, 0) + 1
        name, fn, label = build_provider(spec, counts[seat_key],
                                         text_mode=text_mode)
        seats.setdefault(name, []).append((label, fn))
    providers = {}
    for name, accounts in seats.items():
        providers[name] = accounts[0][1] if len(accounts) == 1 \
            else AccountPool(accounts)
    return providers


def build_solvers(specs):
    """specs -> {seat name: solver callable} for intake mode: same
    seats and account pools as build_providers, but each callable
    answers in plain Markdown (see build_provider's text_mode)."""
    return build_providers(specs, text_mode=True)
